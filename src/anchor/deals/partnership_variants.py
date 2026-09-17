"""Phase 7 Gate P7.9 Stage 2 -- the Partnership variant service.

Restates ``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Sections 2, 13 and
17.2, under ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md``
Sections 3 (P-4, P-8), 13, 14 and 15.4; those documents govern on any
discrepancy.

The one place a *persisted* Partnership meets the accepted Stage 1 engine::

    the structured variant                    P7.8B, unchanged:
            |                                 ``analyze_structured_variant``
            |                                 (the Project variant, then the
            |                                 P7.8A executor)
            v
    the resolved Partnership                  the Investment's Base Partnership,
            |                                 replaced whole by the Strategy's
            |                                 own where it states one
            v
    execute_partnership(partnership, structured.result)       PartnershipResult

**One route to the Common Equity Cash Flow.** The Partnership allocates
``StructuredCapitalResult.common_equity.cash_flows`` through the Stage 1 seam,
for either analysis root, with or without structured positions. Nothing here
reads a Project ``levered_cash_flows``, runs a Capital Structure executor or
imports the Stage 1 waterfall internals: the seam is ``execute_partnership``,
reached only through ``analyze_structured_variant``.

**Downstream only (P-4).** Editing a Partnership cannot change a Project result,
a structured result, or either of their fingerprints: only the Partnership
result and the Partner perspective move.

**No Partnership, no key (FP-2).** A variant with no resolved Partnership has
no Partnership result and no Partnership fingerprint. It is reported with
``partnership = None``, never with an empty or zero-filled result.

**Recomputed, never cached (Q14).** No Partnership result is stored.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ..analysis.strategy import (
    BASE_STRATEGY_ID,
    StrategyDefinition,
    resolve_partnership,
    strategy_partnership,
)
from ..partnership import Partner, Partnership, PartnershipResult, PartnerRole, execute_partnership
from . import store
from .fingerprint import fingerprint_partnership_source
from .structured_variants import (
    StructuredRootKind,
    analyze_structured_variant,
    structured_variant_fingerprint,
)


class PartnershipSource(StrEnum):
    """Where the resolved Partnership statement came from: the Investment's Base
    Partnership, or this Strategy's own whole replacement (which may be the
    explicit "no Partnership")."""

    BASE = "base"
    STRATEGY = "strategy"


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedPartnership:
    """The Partnership one variant allocates with -- ``None`` when it has
    none -- and which owner stated that."""

    partnership: Partnership | None
    source: PartnershipSource


@dataclass(frozen=True, slots=True, kw_only=True)
class PartnershipVariantFingerprint:
    """The three layered fingerprints of one Partnership variant, beside its
    identity.

    ``project_source_fingerprint`` and ``structured_source_fingerprint`` are the
    existing P7.2 / P7.4 / P7.6 and P7.8B fingerprints, unchanged.
    ``partnership_source_fingerprint`` is the structured one plus the resolved
    Partnership's economics, and is ``None`` when no Partnership resolves
    (FP-2)."""

    investment_id: str
    strategy_id: str
    scenario_id: str
    root_kind: StructuredRootKind
    unit_ids: tuple[str, ...]
    partnership: Partnership | None
    partnership_source: PartnershipSource
    project_source_fingerprint: str
    structured_source_fingerprint: str
    partnership_source_fingerprint: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class PartnershipVariantAnalysis:
    """One analysed Partnership variant: the identity, the layered
    fingerprints, the resolved Partnership and the Stage 1 result.

    ``result`` is ``None`` exactly when ``partnership`` is ``None``. A result
    whose upstream Common Equity is unavailable is a successful analysis with
    ``UNAVAILABLE`` status, never an error. ``project_cache_status`` is
    operational metadata about the Project half only."""

    investment_id: str
    strategy_id: str
    scenario_id: str
    root_kind: StructuredRootKind
    unit_ids: tuple[str, ...]
    hold_period: int
    partnership: Partnership | None
    partnership_source: PartnershipSource
    project_source_fingerprint: str
    structured_source_fingerprint: str
    partnership_source_fingerprint: str | None
    project_cache_status: str
    result: PartnershipResult | None


@dataclass(frozen=True, slots=True, kw_only=True)
class PartnerPerspective:
    """One addressable ``PARTNER(partner_id)`` perspective of an Investment.

    The union of the stable partner ids in the Investment's Base Partnership and
    in every Strategy's own, with the role that identity keeps everywhere (P-8,
    enforced at every save). ``name`` is presentation: the Base Partnership's
    name where it has one, else the first Strategy's, so the analyst never has to
    select an opaque id.

    ``present_in_base`` and ``strategy_ids`` say where the partner is actually
    present once each Strategy is resolved -- a Strategy that inherits the Base
    Partnership includes every Base partner, and one that states "no
    Partnership" includes none -- which is what makes a matrix cell "not
    applicable to this perspective". No financial figure is computed here."""

    partner_id: str
    name: str
    role: PartnerRole
    present_in_base: bool
    strategy_ids: tuple[str, ...]


def _strategy(investment_id: str, strategy_id: str, db_path: Path | None) -> StrategyDefinition | None:
    """The persisted Strategy the key names, or ``None`` for the reserved
    implicit Base key."""

    if strategy_id == BASE_STRATEGY_ID:
        return None
    return store.get_strategy(investment_id, strategy_id, db_path=db_path).strategy


def resolve_variant_partnership(
    investment_id: str, strategy_id: str, *, db_path: Path | None = None
) -> ResolvedPartnership:
    """The Partnership the variant allocates with: the Investment's Base
    Partnership, replaced **whole** by this Strategy's own statement where it
    states one (ST-2). Read-only, and it materializes nothing."""

    strategy = _strategy(investment_id, strategy_id, db_path)
    base = store.get_base_partnership(investment_id, db_path=db_path)
    return ResolvedPartnership(
        partnership=resolve_partnership(base, strategy),
        source=PartnershipSource.BASE
        if strategy_partnership(strategy) is None
        else PartnershipSource.STRATEGY,
    )


def _partnership_fingerprint(
    structured_source_fingerprint: str, partnership: Partnership | None
) -> str | None:
    """The Partnership fingerprint, or ``None`` when there is no Partnership to
    fingerprint (FP-2)."""

    if partnership is None:
        return None
    return fingerprint_partnership_source(
        structured_source_fingerprint=structured_source_fingerprint, partnership=partnership
    )


def partnership_variant_fingerprint(
    investment_id: str, strategy_id: str, scenario_id: str, *, db_path: Path | None = None
) -> PartnershipVariantFingerprint:
    """The layered fingerprints of one Partnership variant, without executing
    anything. The Project and structured fingerprints are P7.8B's own."""

    resolved = resolve_variant_partnership(investment_id, strategy_id, db_path=db_path)
    structured = structured_variant_fingerprint(
        investment_id, strategy_id, scenario_id, db_path=db_path
    )
    return PartnershipVariantFingerprint(
        investment_id=investment_id,
        strategy_id=strategy_id,
        scenario_id=scenario_id,
        root_kind=structured.root_kind,
        unit_ids=structured.unit_ids,
        partnership=resolved.partnership,
        partnership_source=resolved.source,
        project_source_fingerprint=structured.project_source_fingerprint,
        structured_source_fingerprint=structured.structured_source_fingerprint,
        partnership_source_fingerprint=_partnership_fingerprint(
            structured.structured_source_fingerprint, resolved.partnership
        ),
    )


def analyze_partnership_variant(
    investment_id: str, strategy_id: str, scenario_id: str, *, db_path: Path | None = None
) -> PartnershipVariantAnalysis:
    """Analyse one Partnership variant end to end.

    Raises what each layer raises, and never blurs them: the Project and
    structured refusals of ``analyze_structured_variant`` unchanged, then the
    Stage 1 engine's ``PartnershipValidationError`` or
    ``PartnershipExecutionError`` for a Partnership it cannot run over this
    Common Equity Cash Flow.

    An **unavailable Common Equity Cash Flow** is none of those: the analysis
    succeeds and the result is ``UNAVAILABLE`` with the upstream reason and
    requirement ids (Section 13)."""

    resolved = resolve_variant_partnership(investment_id, strategy_id, db_path=db_path)
    structured = analyze_structured_variant(
        investment_id, strategy_id, scenario_id, db_path=db_path
    )
    result = (
        None
        if resolved.partnership is None
        else execute_partnership(resolved.partnership, structured.result)
    )
    return PartnershipVariantAnalysis(
        investment_id=investment_id,
        strategy_id=strategy_id,
        scenario_id=scenario_id,
        root_kind=structured.root_kind,
        unit_ids=structured.unit_ids,
        hold_period=structured.hold_period,
        partnership=resolved.partnership,
        partnership_source=resolved.source,
        project_source_fingerprint=structured.project_source_fingerprint,
        structured_source_fingerprint=structured.structured_source_fingerprint,
        partnership_source_fingerprint=_partnership_fingerprint(
            structured.structured_source_fingerprint, resolved.partnership
        ),
        project_cache_status=structured.project_cache_status,
        result=result,
    )


def partner_perspectives(
    investment_id: str, *, db_path: Path | None = None
) -> tuple[PartnerPerspective, ...]:
    """Every addressable Partner perspective of the Investment: the union of
    the stable partner ids its Base Partnership and its Strategies' own
    Partnerships hold, in ``partner_id`` order (Section 15.5).

    The union, not an intersection: a partner only one Strategy states is still
    a perspective, and under the Strategies that do not hold it the matrix
    reports "not applicable to this perspective". No financial metric is
    computed here."""

    stated = store.list_investment_partnerships(investment_id, db_path=db_path)
    stating = {entry.strategy_id for entry in stated.strategies}
    inheriting = [
        record.strategy.strategy_id
        for record in store.list_strategies(investment_id, db_path=db_path)
        if record.strategy.strategy_id not in stating
    ]

    named: dict[str, Partner] = {}
    in_base: set[str] = set()
    holders: dict[str, list[str]] = {}
    if stated.base is not None:
        for partner in stated.base.partners:
            named.setdefault(partner.partner_id, partner)
            in_base.add(partner.partner_id)
            holders.setdefault(partner.partner_id, []).extend(inheriting)
    for entry in stated.strategies:
        if entry.partnership is None:
            continue
        for partner in entry.partnership.partners:
            named.setdefault(partner.partner_id, partner)
            holders.setdefault(partner.partner_id, []).append(entry.strategy_id)

    return tuple(
        PartnerPerspective(
            partner_id=partner_id,
            name=named[partner_id].name,
            role=named[partner_id].role,
            present_in_base=partner_id in in_base,
            strategy_ids=tuple(sorted(set(holders.get(partner_id, ())))),
        )
        for partner_id in sorted(named)
    )


def partner_perspective(
    investment_id: str, partner_id: str, *, db_path: Path | None = None
) -> PartnerPerspective | None:
    """One Partner perspective by id, or ``None`` when no stored Partnership of
    this Investment holds it."""

    for perspective in partner_perspectives(investment_id, db_path=db_path):
        if perspective.partner_id == partner_id:
            return perspective
    return None


def resolved_partner(partnership: Partnership | None, partner_id: str) -> Partner | None:
    """The partner ``partner_id`` in one resolved Partnership, or ``None`` when
    that variant has no Partnership or its Partnership does not hold the partner
    -- which is exactly what makes a cell not applicable to the perspective,
    never zero and never invalid."""

    if partnership is None:
        return None
    for partner in partnership.partners:
        if partner.partner_id == partner_id:
            return partner
    return None
