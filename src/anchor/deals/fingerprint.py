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
from collections.abc import Iterable, Mapping
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
from ..partnership.contracts import (
    CatchUpTerms,
    ExplicitSplit,
    HurdleTerms,
    IrrHurdle,
    MoicHurdle,
    Partnership,
    ProRataByContribution,
    WaterfallTier,
)
# P7.10 Stage 2. The valuation *shapes* only -- ``anchor.valuation.engine`` and
# ``anchor.valuation.funding`` are deliberately absent, exactly as no engine
# calculation module is imported here: this module hashes already-resolved
# values, it never resolves one.
from ..valuation.contracts import (
    AnalystValue,
    DirectCap,
    InvestmentValuationResult,
    UnitValuationResult,
    ValuationTimepoint,
)
# The memo *shapes* only. ``anchor.memo`` imports nothing from this package, so
# naming its contracts here creates no cycle -- and typing them honestly is what
# lets a field added to a memo be a fingerprint change someone notices.
from ..memo.contracts import (
    InvestmentMemoDraft,
    InvestmentMemoVersion,
    MemoEvidenceReference,
    MemoItem,
    MemoRiskItem,
    MemoTermItem,
    SelectedDecision,
)
from ..analysis.scenario import ScenarioDefinition
from ..analysis.strategy import StrategyDefinition
from .capital_structure_codec import PositionTermsKind, amount_rule_kind
from .partnership_codec import condition_kind, recipient_kind, split_rule_kind, subject_kind
from .valuation_codec import valuation_method_kind

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

#: The keys a Partnership fingerprint's payload records (P7.9 Stage 2): the
#: structured source fingerprint it is downstream of, and the resolved
#: Partnership's canonical economics. No economic contract has either field.
_STRUCTURED_FINGERPRINT_KEY = "structured_source_fingerprint"
_PARTNERSHIP_KEY = "partnership"


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
    *,
    project_source_fingerprint: str,
    capital_structure: CapitalStructure,
    consumed_valuations: Mapping[str, InvestmentValuationResult] | None = None,
) -> str:
    """The source fingerprint of one structured variant: the Project variant's
    own fingerprint, the resolved Capital Structure's economics, and -- from
    P7.10 Stage 2 -- any valuation a ``PctOfValue`` rule actually consumes.

    **An empty structure collapses to the Project fingerprint itself** (FP-2),
    returned unchanged rather than hashed with an empty payload. That is what
    makes structured capital neutral: a Deal, a Strategy or an Investment with
    no authored position has one financial identity, not two.

    **Every pre-P7.10 digest is preserved byte for byte.** ``consumed_valuations``
    joins the payload only when it is non-empty, exactly as the D6.5 Business
    Plan rule joins only a non-empty plan. A structure with no ``PctOfValue``
    rule -- which is every structure that existed before this gate -- hashes the
    identical payload it hashed at P7.8B, so no stored fingerprint, snapshot or
    published identity is invalidated by this gate's existence.

    **Why it participates at all.** Section 6: "a valuation consumed by
    ``PctOfValue`` is an economic dependency of the resolved Capital Structure
    and therefore participates in its financial identity and downstream
    invalidation." Changing the cap rate of a consumed timepoint changes the
    dollars a position is funded with; a structured identity that did not move
    would report that changed analysis as the same one. A *report-only*
    valuation no position consumes is deliberately absent: it changes valuation
    and memo freshness, and not the underlying Acquisition analysis."""

    if not isinstance(project_source_fingerprint, str) or not project_source_fingerprint:
        raise UnfingerprintableValueError(project_source_fingerprint)
    if not isinstance(capital_structure, CapitalStructure):
        raise UnfingerprintableValueError(capital_structure)
    if not capital_structure.positions:
        return project_source_fingerprint
    payload: dict[str, Any] = {
        _PROJECT_FINGERPRINT_KEY: project_source_fingerprint,
        _CAPITAL_STRUCTURE_KEY: capital_structure_payload(capital_structure),
    }
    if consumed_valuations:
        payload[_CONSUMED_VALUATIONS_KEY] = consumed_valuation_payload(consumed_valuations)
    return _fingerprint_json(payload)


# =============================================================================
# Phase 7 Gate P7.9 Stage 2 -- the Partnership source fingerprint
#
# ``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Section 17.2 and
# ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section 15.4
# (FP-1, FP-2, Section 15.5). The Partnership is a layer *downstream* of the
# structured capital layer, so it gets its own fingerprint:
#
#     structured source fingerprint     P7.8B, UNCHANGED -- it never learns that
#             |                         a Partnership exists
#             v
#     partnership source fingerprint = f(structured fingerprint, the RESOLVED
#                                        Partnership's canonical economics)
#
# Editing a Partnership therefore invalidates the Partnership result and the
# Partner Decision Matrix, and nothing upstream.
#
# **FP-2.** With no resolved Partnership there is no Partnership fingerprint at
# all: this function requires one, and the variant service reports ``None``
# rather than hashing an absence.
#
# **FP-1.** Only economics enter. Included: partner ids, investor classes and
# commitment shares; the contribution rule; the benchmark shares; the sorted
# promote participants; each tier's id, sequence, kind and split rule with its
# shares; each hurdle's subject, conditions (accrual convention and SIMPLE order
# included) and combinator; each catch-up's recipient and target. Excluded:
# partner and tier names, and ``role``, which is reporting only.
#
# **Order (Section 15.5).** Partners, benchmark shares and split shares by
# ``partner_id``; promote participants sorted; tiers by ``sequence``; conditions
# by ``condition_id``. Authored list order and storage order never reach the
# digest.
# =============================================================================


def _shares_payload(shares: Iterable[object]) -> list[list[Any]]:
    """A share table as ``[partner_id, share]`` pairs in ``partner_id`` order."""

    return sorted(
        ([getattr(row, "partner_id"), float(getattr(row, "share"))] for row in shares),
        key=lambda pair: pair[0],
    )


def _split_payload(split: object) -> dict[str, Any]:
    """One tier split rule, by kind. An unknown rule is refused rather than
    hashed as something else."""

    match split:
        case ExplicitSplit():
            return {"kind": split_rule_kind(split).value, "shares": _shares_payload(split.shares)}
        case ProRataByContribution():
            return {"kind": split_rule_kind(split).value}
        case _:
            raise UnfingerprintableValueError(split)


def _condition_payload(condition: object) -> dict[str, Any]:
    match condition:
        case IrrHurdle():
            return {
                "kind": condition_kind(condition).value,
                "condition_id": condition.condition_id,
                "rate": float(condition.rate),
                "accrual_convention": condition.accrual_convention.value,
                "simple_distribution_order": (
                    None
                    if condition.simple_distribution_order is None
                    else condition.simple_distribution_order.value
                ),
            }
        case MoicHurdle():
            return {
                "kind": condition_kind(condition).value,
                "condition_id": condition.condition_id,
                "multiple": float(condition.multiple),
            }
        case _:
            raise UnfingerprintableValueError(condition)


def _hurdle_payload(hurdle: HurdleTerms | None) -> dict[str, Any] | None:
    if hurdle is None:
        return None
    subject = hurdle.hurdle_subject
    return {
        "hurdle_subject": {
            "kind": subject_kind(subject).value,
            "partner_id": subject.partner_id,
            "investor_class": subject.investor_class,
            "account": None if subject.account is None else subject.account.value,
        },
        "conditions": sorted(
            (_condition_payload(condition) for condition in hurdle.conditions),
            key=lambda item: item["condition_id"],
        ),
        "combinator": hurdle.combinator.value,
    }


def _catch_up_payload(catch_up: CatchUpTerms | None) -> dict[str, Any] | None:
    if catch_up is None:
        return None
    recipient = catch_up.recipient
    return {
        "recipient": {
            "kind": recipient_kind(recipient).value,
            "partner_id": recipient.partner_id,
            "investor_class": recipient.investor_class,
        },
        "target_profit_share": float(catch_up.target_profit_share),
    }


def _tier_payload(tier: WaterfallTier) -> dict[str, Any]:
    """One tier's economics. ``name`` is deliberately absent (FP-1); the stable
    ``tier_id`` is present, because the tier audit addresses it."""

    return {
        "tier_id": tier.tier_id,
        "sequence": int(tier.sequence),
        "kind": tier.kind.value,
        "split": _split_payload(tier.split),
        "hurdle": _hurdle_payload(tier.hurdle),
        "catch_up": _catch_up_payload(tier.catch_up),
    }


def partnership_payload(partnership: Partnership) -> dict[str, Any]:
    """The canonical economic form of a resolved Partnership. Partner names and
    roles and tier names never appear; every list is in its canonical order."""

    if not isinstance(partnership, Partnership):
        raise UnfingerprintableValueError(partnership)
    return {
        "partners": [
            {
                "partner_id": partner.partner_id,
                "investor_class": partner.investor_class,
                "commitment_share": float(partner.commitment_share),
            }
            for partner in sorted(partnership.partners, key=lambda item: item.partner_id)
        ],
        "contribution_rule": partnership.contribution_rule.value,
        "promote_benchmark": _shares_payload(partnership.promote_benchmark.shares),
        "promote_participant_ids": sorted(partnership.promote_participant_ids),
        "tiers": [
            _tier_payload(tier)
            for tier in sorted(partnership.tiers, key=lambda item: (item.sequence, item.tier_id))
        ],
    }


def fingerprint_partnership_source(
    *, structured_source_fingerprint: str, partnership: Partnership
) -> str:
    """The source fingerprint of one Partnership variant: the structured
    variant's own fingerprint, and the resolved Partnership's economics.

    A Partnership is required. A variant with no resolved Partnership has no
    Partnership fingerprint (FP-2); the caller reports ``None`` instead of
    asking for one."""

    if not isinstance(structured_source_fingerprint, str) or not structured_source_fingerprint:
        raise UnfingerprintableValueError(structured_source_fingerprint)
    return _fingerprint_json(
        {
            _STRUCTURED_FINGERPRINT_KEY: structured_source_fingerprint,
            _PARTNERSHIP_KEY: partnership_payload(partnership),
        }
    )


# =============================================================================
# Phase 7 Gate P7.10 Stage 2 -- the valuation and memo identities
#
# ``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Section 10. P7.10 adds
# *layered* identity rather than widening any existing fingerprint::
#
#     project source fingerprint        P7.2 / P7.4 / P7.6, UNCHANGED
#             |
#     structured source fingerprint     P7.8B, unchanged unless a PctOfValue
#             |                         rule actually consumes a valuation
#             v                         (see ``fingerprint_structured_source``)
#     partnership source fingerprint    P7.9, unchanged
#
#     valuation-definition fingerprint = f(the authored timepoints' economics)
#             |
#     valuation-result fingerprint = f(selected variant fingerprint,
#             |                        definition fingerprint,
#             |                        the resolved values and statuses)
#             v
#     memo-content fingerprint = f(the authored memo, its item ids, its explicit
#             |                    display order, the selected decision, the
#             |                    cited evidence's content)
#             v
#     published-version fingerprint = f(every dependency identity above,
#                                       the immutable version content)
#
# **Prose never reaches a financial identity.** No memo field, item text,
# evidence title or narrative of any kind enters the project, structured,
# partnership, valuation-definition or valuation-result fingerprint. A memo can
# therefore be rewritten from end to end without invalidating one number.
#
# **Presentation never reaches any identity that claims to be economic.** A
# valuation ``label`` and a timepoint's display order are excluded from the
# valuation fingerprints by construction -- they are not in the payloads at all,
# so renaming a view cannot invalidate a published memo's financial
# dependencies. Memo item ``display_order`` *is* in the memo-content
# fingerprint, because Section 10 states it is part of the authored memo.
#
# **The IC decision is excluded from the published-version fingerprint**
# (Section 10). The committee records its outcome after publication; doing so
# must not alter the identity of the thing it decided on.
# =============================================================================

#: The keys each P7.10 payload is recorded under. No economic contract has a
#: field of any of these names, so none can collide with one.
_VALUATION_DEFINITIONS_KEY = "valuation_definitions"
_VALUATION_RESULTS_KEY = "valuation_results"
_VARIANT_FINGERPRINT_KEY = "variant_source_fingerprint"
_VALUATION_DEFINITION_FINGERPRINT_KEY = "valuation_definition_fingerprint"
_CONSUMED_VALUATIONS_KEY = "consumed_valuations"
_MEMO_CONTENT_KEY = "memo_content"
_EVIDENCE_KEY = "evidence"
_DEPENDENCIES_KEY = "dependencies"
_VERSION_CONTENT_KEY = "version_content"


def _method_payload(method: object) -> dict[str, Any]:
    """One unit valuation instruction's method, by kind (Section 10).

    Explicit per method: an unknown one is refused rather than hashed as
    something else. ``evidence_id`` participates because Section 10 names the
    *required evidence id* as part of the definition's identity -- repointing an
    analyst-supplied value at a different source is a different valuation, even
    when the amount is unchanged."""

    match method:
        case DirectCap():
            return {"kind": valuation_method_kind(method).value, "cap_rate": float(method.cap_rate)}
        case AnalystValue():
            return {
                "kind": valuation_method_kind(method).value,
                "amount": float(method.amount),
                "evidence_id": method.evidence_id,
            }
        case _:
            raise UnfingerprintableValueError(method)


def valuation_timepoint_payload(timepoint: ValuationTimepoint) -> dict[str, Any]:
    """The canonical economic form of one authored valuation definition.

    Included (Section 10): the timepoint id, its kind, its model month, and
    every unit instruction's unit id and method economics, in ``unit_id`` order.

    **Excluded: ``label``.** It is analyst-facing presentation. Section 5.2 is
    explicit -- "a label change is presentation-only; a model-month change is a
    different valuation definition" -- so renaming a view must never invalidate
    a published memo's financial dependencies.

    **Excluded: authored order.** Instructions sort by ``unit_id``, so a
    permutation of the authored tuple changes nothing. Sorting is not
    deduplication: two instructions for one Unit remain two entries here and are
    refused by the Stage 1 validator, never collapsed."""

    if not isinstance(timepoint, ValuationTimepoint):
        raise UnfingerprintableValueError(timepoint)
    return {
        "timepoint_id": timepoint.timepoint_id,
        "kind": timepoint.kind.value,
        "model_month": int(timepoint.model_month),
        "unit_instructions": [
            {"unit_id": instruction.unit_id, "method": _method_payload(instruction.method)}
            for instruction in sorted(
                timepoint.unit_instructions, key=lambda item: item.unit_id
            )
        ],
    }


def fingerprint_valuation_definitions(timepoints: Iterable[ValuationTimepoint]) -> str:
    """The identity of every valuation definition an Investment states.

    Canonical by ``timepoint_id``, so the analyst's authored order and the
    storage ordinal that preserves it never reach the digest. An Investment that
    states no timepoint has the digest of the empty list -- a real, stable
    identity, because "no valuation is defined" is itself a state a published
    memo can depend on and can later stop matching."""

    return _fingerprint_json(
        {
            _VALUATION_DEFINITIONS_KEY: [
                valuation_timepoint_payload(timepoint)
                for timepoint in sorted(timepoints, key=lambda item: item.timepoint_id)
            ]
        }
    )


def _unit_result_payload(result: UnitValuationResult) -> dict[str, Any]:
    """One Unit's resolved value and status.

    Both halves participate. The value, because it is what the memo cites; the
    status and typed reason, because "this Unit has no value, for this reason"
    is a result a memo can cite just as much as an amount, and a later state in
    which it *does* resolve must not read as unchanged.

    ``analyst_supplied`` participates too: the same number reached by an Anchor
    direct capitalisation and by an analyst's own statement are different
    results (Section 5.4), and a fingerprint that could not tell them apart
    would let one be relabelled as the other."""

    return {
        "unit_id": result.unit_id,
        "model_month": int(result.model_month),
        "method_kind": result.method_kind.value,
        "analyst_supplied": bool(result.analyst_supplied),
        "status": result.status.value,
        "value": None if result.value is None else float(result.value),
        "unavailable_reason": (
            None if result.unavailable_reason is None else result.unavailable_reason.value
        ),
    }


def valuation_result_payload(result: InvestmentValuationResult) -> dict[str, Any]:
    """The canonical form of one resolved valuation at one timepoint.

    ``label`` is excluded here for the same reason it is excluded from the
    definition payload; ``unit_results`` is already in canonical ``unit_id``
    order as Stage 1 produced it, and is re-sorted rather than trusted, so this
    payload cannot inherit an ordering assumption from another layer."""

    if not isinstance(result, InvestmentValuationResult):
        raise UnfingerprintableValueError(result)
    return {
        "timepoint_id": result.timepoint_id,
        "kind": result.kind.value,
        "model_month": int(result.model_month),
        "scope_kind": result.scope_kind.value,
        "status": result.status.value,
        "value": None if result.value is None else float(result.value),
        "unavailable_reason": (
            None if result.unavailable_reason is None else result.unavailable_reason.value
        ),
        "unit_results": [
            _unit_result_payload(unit)
            for unit in sorted(result.unit_results, key=lambda item: item.unit_id)
        ],
    }


def fingerprint_valuation_results(
    *,
    variant_source_fingerprint: str,
    valuation_definition_fingerprint: str,
    results: Iterable[InvestmentValuationResult],
) -> str:
    """The identity of one Analysis Variant's resolved valuations (Section 10).

    Three layers, each named explicitly rather than merged: the variant that
    produced the forward NOIs, the definitions that were resolved, and the
    values and statuses that came out. That is what makes a stale reason
    specific -- a changed cap rate moves the definition layer, and a changed
    Strategy moves the variant layer, and the two are distinguishable."""

    if not isinstance(variant_source_fingerprint, str) or not variant_source_fingerprint:
        raise UnfingerprintableValueError(variant_source_fingerprint)
    if not isinstance(valuation_definition_fingerprint, str) or not valuation_definition_fingerprint:
        raise UnfingerprintableValueError(valuation_definition_fingerprint)
    return _fingerprint_json(
        {
            _VARIANT_FINGERPRINT_KEY: variant_source_fingerprint,
            _VALUATION_DEFINITION_FINGERPRINT_KEY: valuation_definition_fingerprint,
            _VALUATION_RESULTS_KEY: [
                valuation_result_payload(result)
                for result in sorted(results, key=lambda item: item.timepoint_id)
            ],
        }
    )


def consumed_valuation_payload(
    consumed: Mapping[str, InvestmentValuationResult]
) -> list[dict[str, Any]]:
    """The resolved valuations a Capital Structure's ``PctOfValue`` rules
    actually consume, in ``timepoint_id`` order.

    Section 6 is explicit: "a valuation consumed by ``PctOfValue`` is an
    economic dependency of the resolved Capital Structure and therefore
    participates in its financial identity and downstream invalidation". Only
    *consumed* valuations appear -- a report-only timepoint no position reads
    changes valuation and memo freshness, and deliberately not the structured
    identity."""

    return [
        valuation_result_payload(consumed[timepoint_id]) for timepoint_id in sorted(consumed)
    ]


def fingerprint_business_plans(plans: Mapping[str, BusinessPlan]) -> str:
    """The identity of the Business Plans one memo depends on: the Investment's
    own under the key ``""``, and each Unit's under its ``unit_id``.

    A *finer* observation than the Project fingerprint, never a replacement for
    it. A Business Plan edit moves this digest and the Project one; reporting
    this class first lets a stale memo say "the Business Plan changed" instead
    of only "the underwriting changed". It is never used to decide a number --
    ``resolve_business_plan`` remains the only authority on what a plan means."""

    payload: dict[str, Any] = {}
    for scope_id, plan in plans.items():
        if not isinstance(plan, BusinessPlan):
            raise UnfingerprintableValueError(plan)
        payload[scope_id] = _with_business_plan({}, plan).get(_BUSINESS_PLAN_KEY, None)
    return _fingerprint_json({_BUSINESS_PLAN_KEY: payload})


def _overlay_content_payload(content: object) -> Any:
    """One Strategy overlay's content, canonically.

    Every overlay content in the ratified contract is a dataclass, so
    ``dataclasses.asdict`` reaches all of it and a field added to one is covered
    the day it is added. Anything else raises: a content shape with no defined
    canonical form must not be hashed by its ``repr``."""

    if dataclasses.is_dataclass(content) and not isinstance(content, type):
        return dataclasses.asdict(content)
    raise UnfingerprintableValueError(content)


def fingerprint_strategy_definition(strategy: StrategyDefinition | None) -> str:
    """The identity of one selected Strategy's authored statement.

    Included: every overlay's ``unit_id`` and domain with its content, and every
    root overlay's domain with its content, each sorted so authored order never
    participates.

    **Excluded: ``name`` and ``description``.** They are presentation, exactly
    as a position's name and a partner's name are excluded from the P7.8B and
    P7.9 payloads. Renaming a Strategy never invalidates a memo.

    ``None`` is the reserved implicit Base Strategy, which states nothing and
    has a stable identity of its own."""

    if strategy is None:
        return _fingerprint_json({"strategy": None})
    return _fingerprint_json(
        {
            "strategy": {
                "strategy_id": strategy.strategy_id,
                "overlays": sorted(
                    (
                        [overlay.unit_id, overlay.domain.value, _overlay_content_payload(overlay.content)]
                        for overlay in strategy.overlays
                    ),
                    key=lambda entry: (entry[0], entry[1], _fingerprint_json({"content": entry[2]})),
                ),
                "root_overlays": sorted(
                    (
                        [overlay.domain.value, _overlay_content_payload(overlay.content)]
                        for overlay in strategy.root_overlays
                    ),
                    key=lambda entry: (entry[0], _fingerprint_json({"content": entry[1]})),
                ),
            }
        }
    )


def fingerprint_scenario_definition(scenario: ScenarioDefinition | None) -> str:
    """The identity of one selected Scenario's authored statement.

    Included: every override's Unit, target, operation and value, sorted.
    Excluded: ``name`` and ``description``, for the same reason as the Strategy
    above. ``None`` is the reserved implicit Base Scenario."""

    if scenario is None:
        return _fingerprint_json({"scenario": None})
    return _fingerprint_json(
        {
            "scenario": {
                "scenario_id": scenario.scenario_id,
                "overrides": sorted(
                    [
                        override.unit_id,
                        override.target.value,
                        override.operation.value,
                        float(override.value),
                    ]
                    for override in scenario.overrides
                ),
            }
        }
    )


def fingerprint_investment_membership(unit_ids: Iterable[str]) -> str:
    """The identity of which Units an Investment holds.

    Membership is a set: sorted, so its storage order never participates. A Unit
    added to or removed from the Investment changes what the memo is *about*,
    which is why it is reported ahead of every other financial class."""

    return _fingerprint_json({"investment_membership": sorted(unit_ids)})


def fingerprint_unit_underwriting(unit_fingerprints: Mapping[str, str]) -> str:
    """The identity of every member Unit's own resolved underwriting inputs.

    These are the *existing* per-Unit Project fingerprints, read and combined --
    never recomputed and never redefined. This layer adds a name for them so a
    stale memo can say which Unit's underwriting moved."""

    return _fingerprint_json({"underwriting": sorted(unit_fingerprints.items())})


def fingerprint_decision_perspective(
    *, perspective: str, position_id: str | None, partner_id: str | None
) -> str:
    """The identity of the selected decision perspective (Section 7.3)."""

    return _fingerprint_json(
        {
            "decision_perspective": {
                "perspective": perspective,
                "position_id": position_id,
                "partner_id": partner_id,
            }
        }
    )


def evidence_payload(evidence: Iterable[MemoEvidenceReference]) -> list[dict[str, Any]]:
    """The canonical content of a set of Evidence References, by
    ``evidence_id``.

    Included: the source kind, title, reference, as-of date and approval state
    -- the content a claim actually rests on. Approval participates because
    withdrawing approval changes what the memo may present as sourced, which is
    exactly the invalidation Section 8 requires.

    **Excluded: ``display_order``.** It is presentation, so reordering the
    evidence register never invalidates a published memo."""

    return sorted(
        (
            {
                "evidence_id": item.evidence_id,
                "source_kind": item.source_kind.value,
                "title": item.title,
                "reference": item.reference,
                "as_of_date": None if item.as_of_date is None else item.as_of_date.isoformat(),
                "approved": bool(item.approved),
            }
            for item in evidence
        ),
        key=lambda entry: entry["evidence_id"],
    )


def fingerprint_evidence(evidence: Iterable[MemoEvidenceReference]) -> str:
    """The identity of the Evidence References a memo cites (Section 8).

    Evidence changes no financial fingerprint: this digest is a memo dependency
    only, and nothing upstream of the memo reads it."""

    return _fingerprint_json({_EVIDENCE_KEY: evidence_payload(evidence)})


def _claim_evidence_payload(evidence_ids: Iterable[str]) -> list[str]:
    """The evidence one claim rests on, in the analyst's authored order.

    Order participates because it is authored, not presentational: it is the
    order a reader is asked to follow the support in. Re-pointing a claim at a
    different source, adding one or dropping one therefore changes the memo's
    content identity, which is what makes an evidence-link change visible to
    stale analysis (Section 10)."""

    return [str(evidence_id) for evidence_id in evidence_ids]


def _memo_item_payload(item: MemoItem) -> dict[str, Any]:
    return {
        "item_id": item.item_id,
        "section": item.section.value,
        "display_order": int(item.display_order),
        "text": item.text,
        "evidence_ids": _claim_evidence_payload(item.evidence_ids),
    }


def _memo_risk_payload(item: MemoRiskItem) -> dict[str, Any]:
    return {
        "item_id": item.item_id,
        "display_order": int(item.display_order),
        "text": item.text,
        "severity": item.severity.value,
        "residual_risk": item.residual_risk.value,
        "mitigant": item.mitigant,
        "evidence_ids": _claim_evidence_payload(item.evidence_ids),
    }


def _memo_term_payload(item: MemoTermItem) -> dict[str, Any]:
    return {
        "item_id": item.item_id,
        "display_order": int(item.display_order),
        "text": item.text,
        "priority": item.priority.value,
        "evidence_ids": _claim_evidence_payload(item.evidence_ids),
    }


def _selected_valuation_payload(memo: InvestmentMemoDraft | InvestmentMemoVersion) -> list[str]:
    """The valuation views this memo selects for inclusion, sorted.

    A draft states its selection directly; a published version carries the
    selection frozen onto its own valuation rows. Both answer the same question,
    so both reduce to the same sorted set of ``timepoint_id`` here.

    Sorted, not authored-order: which views the memo includes is the content
    question. Where they sit on the page is presentation, and Section 10 keeps
    presentation out of identity."""

    if isinstance(memo, InvestmentMemoDraft):
        selected: Iterable[str] = memo.selected_valuation_timepoint_ids
    else:
        selected = (view.timepoint_id for view in memo.valuations if view.selected)
    return sorted(str(timepoint_id) for timepoint_id in selected)


def _selected_decision_payload(selected: SelectedDecision | None) -> dict[str, Any] | None:
    if selected is None:
        return None
    return {
        "strategy_id": selected.strategy_id,
        "scenario_id": selected.scenario_id,
        "perspective": selected.perspective.value,
        "position_id": selected.position_id,
        "partner_id": selected.partner_id,
    }


def memo_content_payload(
    memo: InvestmentMemoDraft | InvestmentMemoVersion, *, evidence: Iterable[MemoEvidenceReference]
) -> dict[str, Any]:
    """The canonical form of one authored memo (Section 10).

    Included: every authoritative field, every item's stable id and text, the
    **explicit display order** Section 10 names as part of the memo, the
    selected decision, the *content* of the evidence it cites -- so withdrawing
    approval from a cited source invalidates the memo that leaned on it -- the
    **evidence each individual claim rests on**, and the valuation views the
    memo selects for inclusion.

    Claim-level links participate because re-pointing a risk at a different
    appraisal changes what the memo asserts, even when every word and every
    registered source is untouched. The selection participates because which
    valuation views a memo includes decides which ones must resolve before it
    can publish.

    Excluded: ``memo_id``, ``investment_id`` and the timestamps. They identify
    the record, not its content; a memo does not become a different memo by
    being saved again."""

    return {
        "prepared_by": memo.prepared_by,
        "decision_ask": memo.decision_ask,
        "analyst_recommendation": memo.analyst_recommendation.value,
        "executive_summary": memo.executive_summary,
        "execution_complexity": memo.execution_complexity.value,
        "return_on_time_notes": memo.return_on_time_notes,
        "selected_decision": _selected_decision_payload(memo.selected_decision),
        "items": sorted(
            (_memo_item_payload(item) for item in memo.items), key=lambda entry: entry["item_id"]
        ),
        "risk_items": sorted(
            (_memo_risk_payload(item) for item in memo.risk_items),
            key=lambda entry: entry["item_id"],
        ),
        "term_items": sorted(
            (_memo_term_payload(item) for item in memo.term_items),
            key=lambda entry: entry["item_id"],
        ),
        "evidence": evidence_payload(evidence),
        "selected_valuations": _selected_valuation_payload(memo),
    }


def fingerprint_memo_content(
    memo: InvestmentMemoDraft | InvestmentMemoVersion, *, evidence: Iterable[MemoEvidenceReference]
) -> str:
    """The memo-content fingerprint (Section 10).

    Excludes the generated report entirely: no PDF byte, page number or rendered
    layout participates, because none of them is authored content. Stage 2
    generates no report at all."""

    return _fingerprint_json({_MEMO_CONTENT_KEY: memo_content_payload(memo, evidence=evidence)})


def fingerprint_published_version(
    *, memo_content_fingerprint: str, dependencies: Iterable[tuple[str, str, str]]
) -> str:
    """The published-version fingerprint (Section 10).

    ``dependencies`` is the version's whole dependency ledger as
    ``(dependency_class, scope_id, fingerprint)`` triples, sorted, so the ledger
    the version recorded is itself part of the version's identity.

    **The Investment Committee decision is deliberately absent.** It is entered
    after publication and recording it must not change the identity of the
    package the committee decided on."""

    if not isinstance(memo_content_fingerprint, str) or not memo_content_fingerprint:
        raise UnfingerprintableValueError(memo_content_fingerprint)
    return _fingerprint_json(
        {
            _VERSION_CONTENT_KEY: memo_content_fingerprint,
            _DEPENDENCIES_KEY: sorted([str(a), str(b), str(c)] for a, b, c in dependencies),
        }
    )
