"""Persistence Phase A / Detailed Operating Model V2.1 Gate 5b -- Deal
contracts.

Like ``anchor.engine.contracts`` and ``anchor.analysis.contracts``, this
module performs no calculation and no I/O of its own -- it only describes
the shape of a saved deal. ``Deal.inputs`` (Quick) and ``Deal.terms`` /
``Deal.detailed_operating_inputs`` (Detailed) nest the existing, frozen
``AcquisitionInputs`` / ``AcquisitionTerms`` / ``DetailedOperatingInputs``
contracts directly rather than flattening or re-declaring their fields, so a
saved deal's assumptions are always the exact same validated shape the
engine already consumes -- never a parallel representation that could drift
from it.

Owner Return Metrics V3 Gate A6: a ``Deal`` may also carry
``analysis_snapshot``/``ai_snapshot`` -- a CACHE of the last successful
deterministic analysis / AI Analyst output for these exact assumptions (and,
for ``ai_snapshot``, this exact ``deal_context``), never a new source of
truth. Reopening a deal still means the assumptions remain resubmittable to
the existing, unmodified engine entry point (``analyze_acquisition`` or
``analyze_detailed_acquisition``) at any time -- the engine remains the sole
authority for every derived number; the snapshot only lets the UI show the
*last* such result immediately, without forcing a re-run. ``anchor.deals``
still never imports an ``anchor.engine`` *calculation* module (``acquisition``/
``debt``/``noi``/``returns``/``operating_projection``) and performs no
calculation of its own here -- ``AcquisitionResults``/``DetailedAcquisitionResults``
(from ``anchor.engine.contracts``) and ``AIAnalysis`` (from ``anchor.ai.
contracts``) are imported purely as pre-existing, calculation-free *result
shapes* to type what this module stores, exactly as ``anchor.ai.contracts``
already imports ``anchor.engine.contracts`` for the same reason.

One domain-level ``Deal`` shape represents both operating modes, per
``operating_mode``: a ``QUICK`` deal has ``inputs`` populated and ``terms``/
``detailed_operating_inputs`` both ``None``; a ``DETAILED`` deal has
``terms``/``detailed_operating_inputs`` populated and ``inputs`` ``None`` --
never a fabricated ``AcquisitionInputs`` with a placeholder ``current_noi``/
``noi_growth``/``occupancy``. See ``docs/detailed_operating_model_v2_1_architecture.md``
Section 4 and Section 6 for the resolution this mirrors at the persistence
layer. ``analysis_snapshot`` mirrors this same split: ``AcquisitionResults``
for a ``QUICK`` deal, ``DetailedAcquisitionResults`` (operating projection +
results) for a ``DETAILED`` deal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..ai.contracts import AIAnalysis
from ..contracts import (
    AcquisitionInputs,
    AcquisitionTerms,
    DetailedOperatingInputs,
    OperatingMode,
    UnsupportedOperatingModeError,
)
from ..analysis import (
    Lease,
    LeaseLevelOperatingInputs,
    LeaseLevelPropertyInputs,
    MarketLeasingAssumptions,
    Suite,
)
from ..analysis.contracts import OneWaySensitivityResult, TwoWaySensitivityResult
from ..analysis.scenario import ScenarioDefinition
from ..analysis.strategy import StrategyDefinition
from ..business_plan import BusinessPlan
from ..engine.contracts import AcquisitionResults, DetailedAcquisitionResults
from ..investment.contracts import InvestmentTransactionCost, InvestmentUnitMembership


# =============================================================================
# D5.8A -- persisted derived analytical state
#
# A completed analytical result belongs to the Deal that produced it, so the
# latest successful Lease-Level sensitivity run survives navigation, a browser
# refresh and an application restart. These four contracts describe exactly what
# is stored for one such run, and nothing more.
#
# **Configuration, not assumptions.** A sensitivity configuration is an
# analytical question the analyst asked -- which metric, which target, which
# candidate values -- never an underwriting input. It reaches no engine and no
# fingerprint; the fingerprint that guards a snapshot is computed from the
# deal's own assumptions, exactly as every other snapshot's already is.
#
# **The candidate values are the strings the analyst actually submitted.** The
# authoritative response already carries the same values on the wire scale, in
# the same order, and that is what every number in the result was produced
# from. What it cannot carry back is how the analyst *wrote* them -- ``6.25``
# for an exit cap the wire spells ``0.0625`` -- and the candidate editor has to
# be restored exactly as it was submitted, not re-derived from a scale
# conversion this layer is not allowed to perform. So the visible values are
# stored as the free text they are, beside the authoritative response, and
# neither is computed from the other.
#
# **No ladder metadata.** Centre/step/count populate the candidate fields and
# are never submitted, so there is nothing about them to persist: the visible
# absolute candidate list is the configuration that was actually run.
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class OneWaySensitivityConfiguration:
    """The one-way question that was asked: which metric, which target, and
    the visible candidate values, in the analyst's own order."""

    metric: str
    assumption: str
    values: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class OneWaySensitivitySnapshot:
    """One completed one-way run: the configuration submitted and the
    authoritative response it produced, stored and restored together as a
    single atomic snapshot -- never a configuration paired with some other
    run's result."""

    configuration: OneWaySensitivityConfiguration
    result: OneWaySensitivityResult


@dataclass(frozen=True, slots=True, kw_only=True)
class TwoWaySensitivityConfiguration:
    """The two-way question that was asked. Rows and columns are distinct
    axes and are stored as such -- a transposed restore would be a different
    question with the same numbers."""

    metric: str
    row_assumption: str
    row_values: tuple[str, ...]
    column_assumption: str
    column_values: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class TwoWaySensitivitySnapshot:
    """One completed two-way run, atomic in exactly the sense
    ``OneWaySensitivitySnapshot`` is."""

    configuration: TwoWaySensitivityConfiguration
    result: TwoWaySensitivityResult


@dataclass(frozen=True, slots=True, kw_only=True)
class Deal:
    """One saved, named acquisition deal, Quick or Detailed.

    ``id`` is a server-generated identifier, opaque to callers.

    For a ``QUICK`` deal: ``inputs`` is the exact ``AcquisitionInputs``
    contract the Quick engine entry point already consumes; ``terms`` and
    ``detailed_operating_inputs`` are ``None``.

    For a ``DETAILED`` deal: ``terms`` and ``detailed_operating_inputs`` are
    the exact contracts the Detailed engine entry point already consumes;
    ``inputs`` is ``None`` -- a Detailed deal never has an
    ``AcquisitionInputs`` instance, matching the engine-layer resolution
    (Gate 3) exactly.

    ``deal_context`` (Gate A4) is optional, user-authored free text
    describing the investment strategy/business plan -- never an
    ``AcquisitionInputs``/``AcquisitionTerms``/``DetailedOperatingInputs``
    field, never read by the deterministic engine, and identical in shape
    for both modes. ``None`` for a legacy deal saved before this field
    existed, or any deal saved with it left blank -- never a fabricated
    default string.

    ``analysis_snapshot``/``ai_snapshot`` (Gate A6) are optional cached
    results, always either ``None`` or already verified (by the store layer
    that produced this ``Deal``) to correspond to this exact ``inputs``/
    ``terms``+``detailed_operating_inputs`` (and, for ``ai_snapshot``, this
    exact ``deal_context``) -- a ``Deal`` never carries a snapshot known to
    be stale. ``None`` means either no analysis/AI has ever been run for
    this deal, or a previously-cached one was invalidated by an assumption/
    context change, or a stored snapshot could not be decoded (a corrupt or
    schema-incompatible cached artifact is always treated as absent, never
    surfaced or allowed to block opening the deal).
    """

    id: str
    name: str
    operating_mode: OperatingMode
    inputs: AcquisitionInputs | None
    terms: AcquisitionTerms | None
    detailed_operating_inputs: DetailedOperatingInputs | None

    # --- Lease-Level (D5.4) -------------------------------------------
    #
    # Its own five fields rather than a reuse of Detailed's, because a
    # Lease-Level deal genuinely has neither ``detailed_operating_inputs``
    # (no ``gross_potential_rent`` -- that is an *output* of the rent roll)
    # nor ``inputs`` (no ``current_noi``, no ``noi_growth``). ``terms`` is
    # shared with Detailed and deliberately not duplicated: the acquisition
    # and debt assumptions mean the same thing in both modes.
    #
    # ``suites`` and ``leases`` are tuples in the request's own order. That
    # order is presentation, not economics -- the engine addresses both by
    # id -- so it is preserved for display and excluded from the
    # fingerprint.
    property_inputs: LeaseLevelPropertyInputs | None = None
    operating_inputs: LeaseLevelOperatingInputs | None = None
    market_leasing: MarketLeasingAssumptions | None = None
    suites: tuple[Suite, ...] | None = None
    leases: tuple[Lease, ...] | None = None

    # --- Business Plan (Phase 6 Gate D6.5) ----------------------------
    #
    # Mode-agnostic deal state: one plan per deal, the same contract in all
    # three modes, and never folded into ``inputs``, ``terms``, the Detailed
    # operating inputs or the rent roll (D6 conventions Section 1). Always a
    # ``BusinessPlan`` -- a deal with no plan, including every legacy deal,
    # carries the empty ``BusinessPlan()``, never ``None``, so no analysis can
    # be handed an absent plan. Tuple order is the analyst's row order:
    # presentation, preserved for display, and excluded from the fingerprint.
    #
    # Defaulted so every existing construction site keeps working unchanged,
    # exactly as the D5.8A snapshot fields are; the store always passes the
    # plan it read.
    business_plan: BusinessPlan = BusinessPlan()

    deal_context: str | None
    analysis_snapshot: AcquisitionResults | DetailedAcquisitionResults | None
    ai_snapshot: AIAnalysis | None

    # --- D5.8A -------------------------------------------------------
    #
    # The latest successful one-way and two-way sensitivity runs, held
    # independently so running one never erases the other. Like every
    # snapshot above, each is either ``None`` or already verified by the
    # store layer to match this deal's exact current assumptions -- a
    # ``Deal`` never carries a sensitivity result known to be stale.
    #
    # Defaulted to ``None`` so every existing construction site keeps
    # working unchanged: a deal with no sensitivity ever run, a mode that
    # does not offer the surface, and a legacy row all reach the same
    # honest "nothing stored" state without any caller naming the field.
    one_way_sensitivity_snapshot: OneWaySensitivitySnapshot | None = None
    two_way_sensitivity_snapshot: TwoWaySensitivitySnapshot | None = None

    created_at: datetime
    updated_at: datetime

    def _lease_level_fields_populated(self) -> bool:
        """Whether any Lease-Level-only field carries a value.

        Guards the modes in both directions: Lease-Level may not borrow
        Quick's or Detailed's fields, and neither may quietly carry a rent
        roll. A deal that held both would have two answers to which engine
        underwrites it.
        """

        return any(
            value is not None
            for value in (
                self.property_inputs,
                self.operating_inputs,
                self.market_leasing,
                self.suites,
                self.leases,
            )
        )

    def __post_init__(self) -> None:
        # D5.1A: total dispatch. Previously ``if QUICK: ... else: <DETAILED
        # invariants>``, which meant any future mode silently inherited
        # Detailed's required-field rules and was reported with Detailed's
        # wording. Each mode now states its own invariants, and a mode with no
        # persisted representation is refused by name rather than by falling
        # into another mode's branch.
        if not isinstance(self.business_plan, BusinessPlan):
            raise ValueError(
                "A Deal's 'business_plan' must be a BusinessPlan instance; a deal "
                "with no plan carries BusinessPlan(), never None."
            )
        if self.operating_mode is OperatingMode.QUICK:
            if self._lease_level_fields_populated():
                raise ValueError(
                    "A QUICK Deal must not have Lease-Level fields populated."
                )
            if self.inputs is None:
                raise ValueError("A QUICK Deal must have 'inputs' populated.")
            if self.terms is not None or self.detailed_operating_inputs is not None:
                raise ValueError(
                    "A QUICK Deal must not have 'terms' or "
                    "'detailed_operating_inputs' populated."
                )
            if self.analysis_snapshot is not None and not isinstance(
                self.analysis_snapshot, AcquisitionResults
            ):
                raise ValueError(
                    "A QUICK Deal's 'analysis_snapshot' must be an "
                    "AcquisitionResults instance, or None."
                )
        elif self.operating_mode is OperatingMode.DETAILED:
            if self._lease_level_fields_populated():
                raise ValueError(
                    "A DETAILED Deal must not have Lease-Level fields populated."
                )
            if self.terms is None or self.detailed_operating_inputs is None:
                raise ValueError(
                    "A DETAILED Deal must have both 'terms' and "
                    "'detailed_operating_inputs' populated."
                )
            if self.inputs is not None:
                raise ValueError("A DETAILED Deal must not have 'inputs' populated.")
            if self.analysis_snapshot is not None and not isinstance(
                self.analysis_snapshot, DetailedAcquisitionResults
            ):
                raise ValueError(
                    "A DETAILED Deal's 'analysis_snapshot' must be a "
                    "DetailedAcquisitionResults instance, or None."
                )
        elif self.operating_mode is OperatingMode.LEASE_LEVEL:
            if (
                self.terms is None
                or self.property_inputs is None
                or self.operating_inputs is None
                or self.market_leasing is None
                or self.suites is None
                or self.leases is None
            ):
                raise ValueError(
                    "A LEASE_LEVEL Deal must have 'terms', 'property_inputs', "
                    "'operating_inputs', 'market_leasing', 'suites' and "
                    "'leases' all populated."
                )
            if self.inputs is not None or self.detailed_operating_inputs is not None:
                raise ValueError(
                    "A LEASE_LEVEL Deal must not have 'inputs' or "
                    "'detailed_operating_inputs' populated -- it has no "
                    "current_noi/noi_growth and no gross_potential_rent."
                )
            if self.analysis_snapshot is not None:
                # D5 decision A, enforced by the contract rather than by
                # convention. Lease-Level results are recomputed on open from
                # approved inputs, so there is no cached financial artifact to
                # go stale and none to be served as current. Making this a
                # constructible state would be the first step toward one.
                raise ValueError(
                    "A LEASE_LEVEL Deal must not carry an 'analysis_snapshot': "
                    "Lease-Level results are recomputed from approved inputs on "
                    "open, never restored from persistence."
                )
        else:
            raise UnsupportedOperatingModeError(
                self.operating_mode, operation="Deal"
            )


class DealNotFoundError(LookupError):
    """Raised when a deal id has no corresponding row in either the Quick
    (``deals``) or Detailed (``detailed_deals``) store."""

    def __init__(self, deal_id: str) -> None:
        self.deal_id = deal_id
        super().__init__(f"No deal found with id {deal_id!r}.")


# =============================================================================
# Phase 7 Gate P7.2 -- the Investment shell and persisted Scenarios
#
# ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 6, 8.2
# and 15.1-15.2 govern.
#
# **Opt-in only (Q4, P-11).** An ordinary standalone Deal has no Investment.
# The first Scenario created for it materializes one *hidden* one-unit
# Investment, and the UI keeps saying "Deal". Nothing on ``Deal`` changes: an
# Investment is a separate parent record, never a field of the deal, so every
# legacy deal, fingerprint and snapshot is untouched (Option A, Q2).
#
# **Membership (Q3).** An existing Deal *is* the Underwriting Unit, and its id
# is the ``unit_id``. A Deal belongs to at most one Investment. Deleting the
# Investment releases the Deal; it is never deleted with it.
#
# **Minimum permanent contract.** P7.2 materializes only the hidden one-unit
# wrapper. There is no name, transaction price, memo, investment-level plan,
# capital structure or partnership here: those are later gates' contracts
# (P7.6+), added when a gate needs them. ``hidden`` is explicit so that a
# future visible Investment is a different, representable state that every
# P7.2 mutation refuses (fails closed) rather than mistakes for a wrapper.
#
# **No Analysis Variant record (Section 7.5, Section 21.3).** Nothing is
# authored on a variant. Its identity is ``(investment, strategy, scenario)``,
# with the Strategy implicitly Base in P7.2, and only fingerprint-guarded cache
# rows are keyed by it (``store.py``'s ``variant_snapshots``).
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class InvestmentUnit:
    """One Underwriting Unit's membership. ``unit_id`` is the existing Deal's
    id; the Deal itself is unchanged and is read through ``get_deal``."""

    unit_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Investment:
    """The optional parent of one or more Deals (Section 6).

    ``id`` is a server-generated opaque identifier, like a deal id. ``hidden``
    is ``True`` for the one-unit wrapper materialized on Scenario opt-in -- the
    only kind of Investment P7.2 creates -- and ``units`` then holds exactly
    one ``InvestmentUnit``. Units are listed in ``unit_id`` order: membership
    is a set, and its order carries no meaning (Section 15.5)."""

    id: str
    hidden: bool
    units: tuple[InvestmentUnit, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class InvestmentScenario:
    """One persisted Scenario and the Investment that owns it.

    ``scenario`` is the exact P7.1 ``ScenarioDefinition`` -- its id, name,
    description and unit-addressed overrides -- never a parallel shape. It has
    already passed the P7.1 stage-1 contract validation for the owning
    Investment's unit. The overrides are in canonical order (unit, then target
    registry order): storage order is never economic meaning (SC-1, P-7).

    Whether the scenario *resolves* over the unit's current inputs is a
    property of the variant, decided when it is fingerprinted or analysed
    (SC-4): the base inputs can change after the scenario is saved."""

    investment_id: str
    scenario: ScenarioDefinition
    created_at: datetime
    updated_at: datetime


class InvestmentNotFoundError(LookupError):
    """No Investment has this id."""

    def __init__(self, investment_id: str) -> None:
        self.investment_id = investment_id
        super().__init__(f"No investment found with id {investment_id!r}.")


class ScenarioNotFoundError(LookupError):
    """No Scenario with this id belongs to this Investment.

    Raised identically whether the scenario does not exist or belongs to
    another Investment: an id supplied by a caller never proves ownership, and
    a foreign scenario's existence is not disclosed."""

    def __init__(self, investment_id: str, scenario_id: str) -> None:
        self.investment_id = investment_id
        self.scenario_id = scenario_id
        super().__init__(
            f"No scenario {scenario_id!r} belongs to investment {investment_id!r}."
        )


# =============================================================================
# Phase 7 Gate P7.4 -- persisted Strategies
#
# A Strategy is owned by the same Investment as the Scenarios (Section 15.1:
# one owner type for all P7 structure). The first Strategy of a standalone Deal
# materializes the hidden one-unit wrapper exactly as a first Scenario does, and
# a Deal that already has one reuses it. The Base Strategy is implicit and is
# never a stored row.
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class InvestmentStrategy:
    """One persisted Strategy and the Investment that owns it.

    ``strategy`` is the exact P7.4 ``StrategyDefinition`` -- its id, name,
    description and unit-addressed overlays -- never a parallel shape. It has
    passed the P7.4 stage-1 contract validation for the owning Investment's
    unit, and its overlays are in canonical order (domain, then unit).

    Whether its variants *resolve* to valid inputs is decided when they are
    fingerprinted or analysed (SC-4): the Base inputs and the Scenarios can
    change after the strategy is saved."""

    investment_id: str
    strategy: StrategyDefinition
    created_at: datetime
    updated_at: datetime


class StrategyNotFoundError(LookupError):
    """No Strategy with this id belongs to this Investment.

    Raised identically whether the strategy does not exist or belongs to
    another Investment, so a foreign strategy's existence is not disclosed.
    The reserved Base key is never a stored Strategy, so it is never found."""

    def __init__(self, investment_id: str, strategy_id: str) -> None:
        self.investment_id = investment_id
        self.strategy_id = strategy_id
        super().__init__(
            f"No strategy {strategy_id!r} belongs to investment {investment_id!r}."
        )


class InvestmentStructureError(RuntimeError):
    """The request needs Investment structure P7.2 does not manage, so it is
    refused rather than guessed at.

    P7.2 creates and edits only the hidden one-unit wrapper. A visible
    Investment (a later gate's state) is never silently edited, collapsed,
    orphaned or deleted by P7.2 code (Section 15.2: a unit of a visible
    Investment must be removed from it before the Deal is deleted).

    P7.6 also raises it for every structural refusal of the visible
    Investment's lifecycle: a Deal that already belongs to an Investment, a
    Unit a Strategy or Scenario still addresses, the removal of the last Unit,
    and deleting a Deal that is a Unit of a visible Investment."""


# =============================================================================
# Phase 7 Gate P7.6 -- the visible Investment
#
# ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 6, 8.2,
# 10, 11 and 15 govern.
#
# A visible Investment is one negotiated transaction over one or more Units.
# It is the same ``investments`` row a hidden wrapper uses -- promoting a
# wrapper reuses it, so its Strategies and Scenarios keep their ids -- with its
# visible state in sidecar records: a name and transaction price, one
# membership per Unit, an Investment-level Business Plan and its transaction
# costs. A hidden wrapper has none of them, and reading one never creates them.
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class VisibleInvestment:
    """One visible Investment and everything it states beyond its Units.

    - ``units``: the memberships, in presentation order (``ordinal``, then
      ``unit_id``). Presentation only: every economic sum orders Units by
      ``unit_id`` instead.
    - ``transaction_price``: validation and reporting only; it never enters a
      cash flow (PP-3).
    - ``business_plan``: the Investment-level D6 plan, the same contract as a
      Deal's, in its own item-ID namespace (BP-7). ``BusinessPlan()`` when
      there is none.
    - ``transaction_costs``: the Investment's closing costs, in the analyst's
      order."""

    id: str
    name: str
    transaction_price: float
    units: tuple[InvestmentUnitMembership, ...]
    business_plan: BusinessPlan
    transaction_costs: tuple[InvestmentTransactionCost, ...]
    created_at: datetime
    updated_at: datetime


class InvestmentUnitNotFoundError(LookupError):
    """No Unit with this id belongs to this Investment. Raised identically
    whether the Deal does not exist or belongs elsewhere, so a caller's id never
    discloses another Investment's structure."""

    def __init__(self, investment_id: str, unit_id: str) -> None:
        self.investment_id = investment_id
        self.unit_id = unit_id
        super().__init__(f"No unit {unit_id!r} belongs to investment {investment_id!r}.")
