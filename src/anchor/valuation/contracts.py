"""Phase 7 Gate P7.10 Stage 1 -- the deterministic valuation shapes.

Restates ``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 4,
5, 6 and 16 under the ratified P7 authority in
``P7_COMPETITION_DECISION_ARCHITECTURE.md``; those documents govern on any
discrepancy. Ratified decisions R-A to R-E are the economics behind every shape
here.

**Shapes only.** Like every other ``contracts`` module in the engine, nothing
here calculates. ``validation`` says whether an authored definition is well
formed and ``engine`` resolves it against one Analysis Variant.

**Identity is opaque and explicit.** A timepoint is named by its
``timepoint_id`` and a Unit by its ``unit_id``. List position is never
economically meaningful: every result is canonicalised by ``unit_id``, so a
permutation of ``unit_instructions`` changes nothing.

**Reporting values.** An ``AS_IS``, ``STABILIZED`` or ``CUSTOM`` valuation is a
reporting value. It creates no sale proceeds and no cash flow. ``EXIT`` is the
one cash-producing valuation, it is the existing D6 terminal result, and it is
read here rather than recalculated (R-B).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar


class ValuationError(Exception):
    """A valuation the engine cannot reach. Raising this is a programming
    error, never an analyst finding: a caller asked for a value the contract
    says is unavailable, instead of reading the typed unavailable result. It is
    not a ``ValueError``, so no caller can mistake it for an invalid
    definition."""


class ValuationIssueCode(StrEnum):
    """Stable reasons an authored valuation definition is not well formed.

    Each is a structural fault of the definition itself, independent of any
    Analysis Variant. A fault that depends on the variant -- a month outside
    that variant's horizon, a Unit that variant does not hold, a non-positive
    forward NOI -- is never an issue here; it is a typed unavailable result
    (``ValuationUnavailableReason``), because the same definition may resolve
    under another Strategy or Scenario."""

    BLANK_TIMEPOINT_ID = "blank_timepoint_id"
    BLANK_INVESTMENT_ID = "blank_investment_id"
    BLANK_LABEL = "blank_label"
    INVALID_MODEL_MONTH = "invalid_model_month"
    KIND_MONTH_MISMATCH = "kind_month_mismatch"
    NO_UNIT_INSTRUCTION = "no_unit_instruction"
    BLANK_UNIT_ID = "blank_unit_id"
    DUPLICATE_UNIT_INSTRUCTION = "duplicate_unit_instruction"
    INVALID_CAP_RATE = "invalid_cap_rate"
    INVALID_ANALYST_AMOUNT = "invalid_analyst_amount"
    BLANK_EVIDENCE_ID = "blank_evidence_id"
    UNSUPPORTED_METHOD = "unsupported_method"


@dataclass(frozen=True, slots=True, kw_only=True)
class ValuationIssue:
    """One deterministic reason an authored definition is not well formed.
    ``unit_id`` names the instruction concerned where one is identifiable, and
    ``field`` locates the finding within the definition."""

    code: ValuationIssueCode
    message: str
    unit_id: str | None = None
    field: str | None = None


class ValuationValidationError(Exception):
    """One or more ``ValuationIssue``. The definition is refused whole: no part
    of it is repaired, defaulted or partially resolved."""

    def __init__(self, issues: tuple[ValuationIssue, ...]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(issue.message for issue in self.issues))


# =============================================================================
# Definitions
# =============================================================================


class ValuationKind(StrEnum):
    """What a stored timepoint means (Section 4; R-A, R-C).

    - ``AS_IS``: the closing-time reporting value, at model month 0. It is not
      the purchase price and is never inferred from it.
    - ``STABILIZED``: an analyst-declared reporting value at a hold-year end.
      Anchor never detects stabilization from occupancy, lease-up, NOI growth,
      construction completion or a Business Plan schedule (R-C).
    - ``CUSTOM``: any other analyst-authored reporting value, at closing or a
      hold-year end.

    ``EXIT`` is deliberately absent: it is reserved, system derived and never
    stored (R-B). See ``ExitValuationView``."""

    AS_IS = "as_is"
    STABILIZED = "stabilized"
    CUSTOM = "custom"


class ValuationMethodKind(StrEnum):
    """The two initial methods (R-D). No DCF, appraisal, comparable-sales or
    AI-estimated method exists; adding one requires its own ratification."""

    DIRECT_CAP = "direct_cap"
    ANALYST_VALUE = "analyst_value"


@dataclass(frozen=True, slots=True, kw_only=True)
class DirectCap:
    """Capitalise the forward NOI of the timepoint's model month at
    ``cap_rate``. ``cap_rate`` is finite and greater than zero."""

    cap_rate: float


@dataclass(frozen=True, slots=True, kw_only=True)
class AnalystValue:
    """An explicit external value the analyst states, not an Anchor engine
    conclusion (Section 5.4). ``amount`` is finite and non-negative;
    ``evidence_id`` names the approved Evidence Reference supporting it and is
    nonblank. Stage 1 validates that identifier structurally and stores no
    evidence: evidence persistence and approval are Stage 2."""

    amount: float
    evidence_id: str


ValuationMethod = DirectCap | AnalystValue


@dataclass(frozen=True, slots=True, kw_only=True)
class UnitValuationInstruction:
    """How one Unit is valued at one timepoint. Exactly one instruction exists
    per included Unit."""

    unit_id: str
    method: ValuationMethod


@dataclass(frozen=True, slots=True, kw_only=True)
class ValuationTimepoint:
    """One analyst-approved valuation definition of one Investment
    (Section 5.1).

    - ``timepoint_id``: stable, opaque and nonblank; unique within the
      Investment.
    - ``investment_id``: the owning Investment. A definition is never valued
      against another Investment's variant.
    - ``model_month``: ``0`` (closing) or a hold-year end ``12y`` (R-A). The
      model month is economic identity: renaming ``label`` is presentation
      only, moving ``model_month`` is a different valuation.
    - ``unit_instructions``: exactly one instruction for every included Unit.
      Their list order is presentation only."""

    timepoint_id: str
    investment_id: str
    kind: ValuationKind
    label: str
    model_month: int
    unit_instructions: tuple[UnitValuationInstruction, ...]


# =============================================================================
# Variant inputs
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class ValuationUnitInputs:
    """One Unit's completed economics under one resolved Analysis Variant, as
    the valuation layer reads them.

    Read only. Every field is the Unit's own already-computed result: this
    layer reproduces no NOI, exit, debt, consolidation or return calculation,
    and the selected Strategy and Scenario reach it only by having produced
    these numbers (Section 5.3).

    ``noi_by_year`` is Years 1..H and ``exit_noi`` the single Year H+1 scalar,
    exactly as the engine contract defines them; ``exit_noi`` is never a member
    of ``noi_by_year``."""

    unit_id: str
    hold_period: int
    noi_by_year: tuple[float, ...]
    exit_noi: float
    exit_cap_rate: float
    exit_value: float
    disposition_costs: float
    net_sale_proceeds: float


@dataclass(frozen=True, slots=True, kw_only=True)
class ValuationVariantInputs:
    """The resolved Analysis Variant a definition is valued against: the
    Investment it belongs to, its common hold horizon, and every member Unit's
    completed economics in canonical ``unit_id`` order.

    ``units`` is the exact membership. A definition that names a Unit this
    variant does not hold, or omits one it does, does not resolve."""

    investment_id: str
    hold_period: int
    units: tuple[ValuationUnitInputs, ...]


# =============================================================================
# Results
# =============================================================================


class ValuationAvailability(StrEnum):
    """Whether a resolved valuation produced a value. ``UNAVAILABLE`` always
    carries a typed reason; it is never rendered as zero and never omitted
    where the omission could mislead (Section 2)."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class ValuationUnavailableReason(StrEnum):
    """Why a valuation produced no value (Section 16).

    - ``NOT_AUTHORED``: no definition exists for the requested timepoint.
    - ``INCOMPLETE_UNITS``: at least one Unit of the Investment has no valid
      value at this model month, so no Investment value exists. A partial
      portfolio sum is never presented as the Investment value (Section 5.5).
    - ``NON_POSITIVE_FORWARD_NOI``: direct capitalisation has no meaning. The
      NOI is never floored, smoothed, annualised or substituted (Section 5.3).
    - ``VARIANT_INVALID``: the variant itself did not resolve.
    - ``UNIT_NOT_IN_VARIANT``: the instruction names a Unit this variant does
      not hold.
    - ``UNIT_NOT_VALUED``: the variant holds a Unit the definition does not
      instruct.
    - ``OUTSIDE_HOLD_HORIZON``: the model month is beyond this variant's hold.
      The same definition may resolve under a longer hold.
    - ``RESERVED_EXIT_MONTH``: the model month is the exit month, whose value
      is the reserved system Exit view and is never a stored definition (R-B).
    - ``NOT_IMPLEMENTED_FOR_SCOPE``: the scope has no implemented valuation.
    - ``EVIDENCE_NOT_APPROVED``: an analyst-supplied value whose Evidence
      Reference is missing or not approved. Stage 1 never produces it -- it
      cannot see evidence -- and the P7.10 Stage 2 evidence gate states it on
      the Unit cell it withholds, with no value. An Investment made incomplete
      by such a cell is ``INCOMPLETE_UNITS``; its member cell keeps this
      precise reason. (Additive amendment, Refinance V1 Stage 2 review
      correction; no valuation arithmetic changes.)"""

    NOT_AUTHORED = "not_authored"
    INCOMPLETE_UNITS = "incomplete_units"
    NON_POSITIVE_FORWARD_NOI = "non_positive_forward_noi"
    VARIANT_INVALID = "variant_invalid"
    UNIT_NOT_IN_VARIANT = "unit_not_in_variant"
    UNIT_NOT_VALUED = "unit_not_valued"
    OUTSIDE_HOLD_HORIZON = "outside_hold_horizon"
    RESERVED_EXIT_MONTH = "reserved_exit_month"
    NOT_IMPLEMENTED_FOR_SCOPE = "not_implemented_for_scope"
    EVIDENCE_NOT_APPROVED = "evidence_not_approved"


class ValuationScopeKind(StrEnum):
    """The scope a value covers. A Unit value and an Investment value are
    always separately labelled, even where a hidden one-unit Investment makes
    them numerically equal (Section 5.5)."""

    UNIT = "unit"
    INVESTMENT = "investment"


@dataclass(frozen=True, slots=True, kw_only=True)
class UnitValuationResult:
    """One Unit's resolved value at one timepoint.

    ``value`` is present only when ``status`` is ``AVAILABLE``; otherwise
    ``unavailable_reason`` and ``unavailable_message`` say why, and nothing is
    zero-filled.

    ``analyst_supplied`` is ``True`` for every ``ANALYST_VALUE`` result and
    ``False`` for every ``DIRECT_CAP`` result, so no presentation layer can
    show an analyst's own number as an Anchor valuation (Section 5.4).
    ``forward_noi`` and ``cap_rate`` are the direct-capitalisation operands and
    are ``None`` for an analyst-supplied value; ``evidence_id`` is the
    converse."""

    unit_id: str
    model_month: int
    method_kind: ValuationMethodKind
    analyst_supplied: bool
    status: ValuationAvailability
    value: float | None
    forward_noi: float | None
    cap_rate: float | None
    evidence_id: str | None
    unavailable_reason: ValuationUnavailableReason | None
    unavailable_message: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class InvestmentValuationResult:
    """One Investment's contemporaneous value at one timepoint (Section 5.5).

    ``value`` is the canonical-order sum of the Unit values, and exists only
    when every member Unit has a valid value at the same ``model_month``.
    ``unit_results`` is always complete and always in ascending ``unit_id``
    order, so an incomplete Investment names the exact Units and reasons that
    made it unavailable.

    Values at different model months are never added or compared here as
    though contemporaneous."""

    timepoint_id: str
    investment_id: str
    kind: ValuationKind
    label: str
    model_month: int
    scope_kind: ValuationScopeKind
    status: ValuationAvailability
    value: float | None
    unit_results: tuple[UnitValuationResult, ...]
    unavailable_reason: ValuationUnavailableReason | None
    unavailable_message: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ExitValuationView:
    """The reserved, read-only system Exit view (R-B).

    It is the existing D6 terminal result of the selected variant, read
    unchanged: no exit value, exit NOI, exit cap rate, disposition cost or net
    sale proceed is recomputed here, so no drift is possible. ``model_month``
    is the exit month ``hold_period * 12``.

    ``exit_cap_rate`` is the Unit's stated exit cap rate, or the Investment's
    ``implied_exit_cap_rate``, which is ``None`` where the consolidation
    reports none. Exit is the only valuation that produces cash."""

    scope_kind: ValuationScopeKind
    unit_id: str | None
    model_month: int
    exit_noi: float
    exit_cap_rate: float | None
    exit_value: float
    disposition_costs: float
    net_sale_proceeds: float


# =============================================================================
# Funding resolution (Section 6; R-E)
# =============================================================================


class FundingResolutionStatus(StrEnum):
    """Whether a ``PctOfValue`` funding resolved to dollars."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


class UnresolvedFundingReason(StrEnum):
    """Why a ``PctOfValue`` funding did not resolve (Section 6).

    Authoring faults -- the definition is missing, belongs to another
    Investment, or is timed or scoped differently from the funding event:

    - ``TIMEPOINT_NOT_FOUND``;
    - ``FOREIGN_INVESTMENT``;
    - ``MODEL_MONTH_MISMATCH``: the funding event's model month is not the
      timepoint's. The initial contract funds only where the two are the same
      model month (R-E); neither is ever moved to the other.
    - ``SCOPE_NOT_COVERED``: the valuation does not cover the position's exact
      scope, so no value of that scope exists to take a percentage of.

    Economic faults -- the authoring is right and the value is unknowable:

    - ``VALUATION_UNAVAILABLE``, carrying the valuation's own typed reason.

    In every case the Funding Requirement is left unresolved and named. It is
    never read as zero, never estimated and never resized."""

    TIMEPOINT_NOT_FOUND = "timepoint_not_found"
    FOREIGN_INVESTMENT = "foreign_investment"
    MODEL_MONTH_MISMATCH = "model_month_mismatch"
    SCOPE_NOT_COVERED = "scope_not_covered"
    VALUATION_UNAVAILABLE = "valuation_unavailable"


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedValuationFunding:
    """A ``PctOfValue`` funding resolved to dollars: ``amount`` is
    ``pct * scope_value`` at ``model_month``, where ``scope_value`` is the
    value of the position's exact scope at the named timepoint.

    The operands are reported beside the amount so a reader can verify the
    arithmetic without re-deriving it."""

    status: ClassVar[FundingResolutionStatus] = FundingResolutionStatus.RESOLVED

    event_id: str
    position_id: str
    timepoint_id: str
    scope_kind: ValuationScopeKind
    unit_id: str | None
    model_month: int
    pct: float
    scope_value: float
    amount: float


@dataclass(frozen=True, slots=True, kw_only=True)
class UnresolvedFundingRequirement:
    """A ``PctOfValue`` funding whose dollars are unknowable (Section 6).

    This is the typed unresolved Funding Requirement the contract names. It is
    deliberately *not* a claim shortfall: P7.7's ``FundingRequirement`` reports
    a contractual claim the eligible cash could not meet, and states both the
    claim due and the cash available. Here the advance itself is unknown, so
    there is no claim amount and no cash figure to state. Inventing either --
    or an amount of zero -- is exactly what the contract forbids.

    ``valuation_reason`` carries the valuation's own typed reason when the
    definition was found and did not resolve; it is ``None`` for an authoring
    fault."""

    status: ClassVar[FundingResolutionStatus] = FundingResolutionStatus.UNRESOLVED

    requirement_id: str
    event_id: str
    position_id: str
    timepoint_id: str
    scope_kind: ValuationScopeKind
    unit_id: str | None
    model_month: int
    pct: float
    reason: UnresolvedFundingReason
    valuation_reason: ValuationUnavailableReason | None
    message: str


ValuationFundingResolution = ResolvedValuationFunding | UnresolvedFundingRequirement
