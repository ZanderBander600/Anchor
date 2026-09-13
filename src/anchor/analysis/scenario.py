"""Phase 7 Gate P7.1 -- the Scenario resolution engine.

Restates ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections
7.1-7.3 and its Section 21 ratification record (Q5, Q10, Q15); that document
governs on any discrepancy.

**A Scenario is what the analyst assumes may happen**: a coherent set of
approved uncertainty overrides on existing Anchor underwriting assumptions. It
is never what the investor chooses. Bid price, hold period, the Business Plan
and the financing structure are Strategy decisions (Section 7.1), and no target
here can reach them.

**Resolve, then run (P-2).** A Scenario changes *inputs*, never outputs::

    ScenarioDefinition + base inputs of one Unit
            |
    stage 1       the scenario contract: identity, unit addressing, targets,
            |     operations and values, and whether each target applies to
            |     this mode and to these inputs
    resolution    one explicit, typed resolver per (target, mode)
            |
    stage 2       the existing validators, on every contract a target changed
            |
    Resolved*Inputs                              existing input contracts only
            |
    analyze_*_acquisition_with_business_plan     the existing D6 entry points
            |
    the existing results contracts

The Scenario layer disappears before the engine boundary. The engine never
learns that a scenario exists, and nothing here computes NOI, debt service, an
exit value, a return or any other financial result. The only arithmetic in
this module is the ratified operations themselves (``_apply_operation``).

**Unit-addressed from P7.1 (Section 7.2, SC-1, SC-5).** Every override names
the Unit (Deal) it applies to, explicitly, even when there is one unit, and a
scenario holds at most one override per ``(unit_id, target)``. P7.1 analyses
one Unit at a time: each resolver is told that Unit's ``unit_id``. An override
addressing any other unit makes the scenario invalid (``UNIT_NOT_IN_VARIANT``).
It is never ignored, filtered out, or applied to the unit being analysed.
Multi-unit resolution later reuses this contract unchanged.

**Absence is Base (P-11).** Ordinary analyses never pass through this module:
a caller with no scenario keeps calling the existing entry points exactly as
before. A scenario with no overrides, resolved deliberately, hands the caller's
own objects to the engine.

**No clipping (SC-4).** A scenario that resolves to invalid underwriting inputs
is invalid. It is reported with the existing validator's own reason, and it is
never clipped, skipped, or answered with a fabricated result.

**Order never matters (SC-1, P-7).** A scenario holds at most one override per
``(unit_id, target)``, so no two operations ever compose. Overrides are
resolved in the registry's declaration order, whatever order they were stored
in.

**Names are not financial (FP-1).** ``scenario_id``, ``name`` and
``description`` are read by stage-1 validation only. No resolver reads them.

**Deliberately not here**, because later gates own it:
- Scenario and Investment persistence, fingerprints, API routes and UI;
- Strategy;
- multi-unit variant orchestration and consolidation;
- probabilities;
- Business Plan targets and per-suite targets.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from math import isfinite
from types import MappingProxyType

from ..business_plan import BusinessPlan
from ..contracts import (
    AcquisitionInputs,
    AcquisitionTerms,
    DetailedOperatingInputs,
    OperatingMode,
)
from ..engine.contracts import AcquisitionResults, DetailedAcquisitionResults
from ..leasing import (
    Lease,
    LeaseLevelOperatingInputs,
    LeaseLevelPropertyInputs,
    LeaseValidationIssue,
    MarketLeasingAssumptions,
    Suite,
    validate_lease_level_inputs,
    validate_lease_level_operating_inputs,
)
from ..validation import (
    InputValidationError,
    validate_acquisition_inputs,
    validate_acquisition_terms,
    validate_detailed_operating_inputs,
)
from .business_plan_analysis import (
    analyze_detailed_acquisition_with_business_plan,
    analyze_lease_level_acquisition_with_business_plan,
    analyze_quick_acquisition_with_business_plan,
)
from .contracts import LeaseLevelAcquisitionResults

# =============================================================================
# Operations
# =============================================================================


class ScenarioOperation(StrEnum):
    """The four ratified scenario operations (Q5, SC-2). There is no fifth.

    - ``SET``:    resolved = value
    - ``ADD``:    resolved = current + value
    - ``SCALE``:  resolved = current * value
    - ``CAP_AT``: resolved = min(current, value)

    ``CAP_AT`` is an **upper cap** and only an upper cap. It never raises the
    current value, it is never reinterpreted as a floor, and it never picks
    ``min`` or ``max`` by a target's direction. A floor would be a new
    operation, which needs its own ratification.

    Values are in the underlying field's own internal units, with no display
    conversion: ``0.0575`` is 5.75%, ``ADD 0.005`` is +50 bps and ``SCALE
    1.10`` multiplies by 1.10.
    """

    SET = "set"
    ADD = "add"
    SCALE = "scale"
    CAP_AT = "cap_at"


def _apply_operation(
    operation: ScenarioOperation, current: float, value: float
) -> float:
    """The ratified semantics, and the only arithmetic in this module.

    The result is a built-in ``float`` because every P7.1 target is a float
    field. That keeps ``SET 1`` and ``SET 1.0`` the same assumption. An
    unknown operation raises; stage 1 has already refused one."""

    match operation:
        case ScenarioOperation.SET:
            resolved = value
        case ScenarioOperation.ADD:
            resolved = current + value
        case ScenarioOperation.SCALE:
            resolved = current * value
        case ScenarioOperation.CAP_AT:
            resolved = min(current, value)
        case _:
            raise ValueError(f"Unknown scenario operation {operation!r}.")
    return float(resolved)


# =============================================================================
# The target registry -- one authority, explicit and finite
# =============================================================================


class ScenarioTarget(StrEnum):
    """Every approved P7.1 scenario target, and nothing else.

    Each wire token is the owning contract's own field name. Where an existing
    sensitivity target has the same name, the two mean the same field of the
    same contract (Section 7.3). Declaration order is the canonical order for
    resolution and for reporting.

    These are **deliberately absent**, because they are Strategy decisions or
    structure (Section 7.3 and the P7.1 gate):
    - ``purchase_price`` (a bid is a decision, even though sensitivity may
      perturb it);
    - ``hold_period``, ``amortization`` and ``io_period``;
    - the acquisition, financing and disposition cost percentages;
    - ``annual_capex_reserve``;
    - every Business Plan item, project capital and owner expenses, and capital
      timing;
    - loan structure;
    - every date and every suite- or lease-specific field.

    Adding a target is an explicit registry decision.
    """

    EXIT_CAP_RATE = "exit_cap_rate"
    INTEREST_RATE = "interest_rate"
    LTV = "ltv"
    NOI_GROWTH = "noi_growth"
    REVENUE_GROWTH = "revenue_growth"
    VACANCY_CREDIT_LOSS_PCT = "vacancy_credit_loss_pct"
    EXPENSE_GROWTH = "expense_growth"
    MARKET_RENT_PSF = "market_rent_psf"
    RENEWAL_PROBABILITY = "renewal_probability"
    RECOVERABLE_EXPENSE_RATIO = "recoverable_expense_ratio"


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioTargetSpec:
    """What the registry states about one target.

    Every field is required, so no target inherits a default operation set or
    a default mode set (Q5).

    ``owner_fields`` names, for each mode the target applies to, the one
    existing contract field its resolver writes. The resolver itself is the
    mode's explicit ``match`` arm below. ``units`` is the internal unit the
    override value must already be in.
    """

    target: ScenarioTarget
    allowed_operations: frozenset[ScenarioOperation]
    owner_fields: Mapping[OperatingMode, str]
    units: str

    @property
    def modes(self) -> frozenset[OperatingMode]:
        return frozenset(self.owner_fields)


#: The one authoritative registry: every ``ScenarioTarget``, each with its own
#: explicit operation whitelist (SC-2). The whitelists are the P7.1 decision
#: that Section 21.3 leaves to this gate, taken within the Section 7.3 rules:
#:
#: - Rates that are market prices (``exit_cap_rate``, ``interest_rate``) take
#:   ``SET`` (an absolute market fact), ``ADD`` (a spread in bps) and ``SCALE``.
#:   ``CAP_AT`` is refused: a cap on a cap rate or a coupon has no clear scenario
#:   meaning.
#: - ``ltv`` is Section 7.3's one BOTH-class target. Leverage *choice* is
#:   Strategy (``FINANCING``), and a Scenario may express only leverage
#:   *availability* (Section 7.6, SC-2). So it takes ``CAP_AT`` alone ("lenders
#:   lend at most 55%"), which can never raise the leverage a strategy chose.
#:   ``SET``, ``ADD`` or ``SCALE`` could raise it, and would override a
#:   decision.
#: - Growth rates and the vacancy / recovery ratios take ``SET`` and ``ADD``. A
#:   growth rate may be zero or negative, and there a multiplier erases or
#:   inverts the intended direction, so ``SCALE`` is refused.
#: - ``market_rent_psf`` takes all four operations, as ratified for P7.1, over
#:   every suite's resolved market rent (Q10, and ``_suite_with_market_rent``).
#: - ``renewal_probability`` takes all four. The resolved value must still be
#:   a valid probability; the existing validator decides that, and nothing here
#:   clips it.
SCENARIO_TARGET_REGISTRY: Mapping[ScenarioTarget, ScenarioTargetSpec] = MappingProxyType(
    {
        ScenarioTarget.EXIT_CAP_RATE: ScenarioTargetSpec(
            target=ScenarioTarget.EXIT_CAP_RATE,
            allowed_operations=frozenset(
                {ScenarioOperation.SET, ScenarioOperation.ADD, ScenarioOperation.SCALE}
            ),
            owner_fields=MappingProxyType(
                {
                    OperatingMode.QUICK: "AcquisitionInputs.exit_cap_rate",
                    OperatingMode.DETAILED: "AcquisitionTerms.exit_cap_rate",
                    OperatingMode.LEASE_LEVEL: "AcquisitionTerms.exit_cap_rate",
                }
            ),
            units="decimal rate (0.0725 is 7.25%)",
        ),
        ScenarioTarget.INTEREST_RATE: ScenarioTargetSpec(
            target=ScenarioTarget.INTEREST_RATE,
            allowed_operations=frozenset(
                {ScenarioOperation.SET, ScenarioOperation.ADD, ScenarioOperation.SCALE}
            ),
            owner_fields=MappingProxyType(
                {
                    OperatingMode.QUICK: "AcquisitionInputs.interest_rate",
                    OperatingMode.DETAILED: "AcquisitionTerms.interest_rate",
                    OperatingMode.LEASE_LEVEL: "AcquisitionTerms.interest_rate",
                }
            ),
            units="decimal rate (0.0575 is 5.75%)",
        ),
        ScenarioTarget.LTV: ScenarioTargetSpec(
            target=ScenarioTarget.LTV,
            allowed_operations=frozenset({ScenarioOperation.CAP_AT}),
            owner_fields=MappingProxyType(
                {
                    OperatingMode.QUICK: "AcquisitionInputs.ltv",
                    OperatingMode.DETAILED: "AcquisitionTerms.ltv",
                    OperatingMode.LEASE_LEVEL: "AcquisitionTerms.ltv",
                }
            ),
            units="decimal ratio (0.55 is 55%)",
        ),
        ScenarioTarget.NOI_GROWTH: ScenarioTargetSpec(
            target=ScenarioTarget.NOI_GROWTH,
            allowed_operations=frozenset({ScenarioOperation.SET, ScenarioOperation.ADD}),
            owner_fields=MappingProxyType(
                {OperatingMode.QUICK: "AcquisitionInputs.noi_growth"}
            ),
            units="decimal annual rate (0.03 is 3%)",
        ),
        ScenarioTarget.REVENUE_GROWTH: ScenarioTargetSpec(
            target=ScenarioTarget.REVENUE_GROWTH,
            allowed_operations=frozenset({ScenarioOperation.SET, ScenarioOperation.ADD}),
            owner_fields=MappingProxyType(
                {OperatingMode.DETAILED: "DetailedOperatingInputs.revenue_growth"}
            ),
            units="decimal annual rate (0.03 is 3%)",
        ),
        ScenarioTarget.VACANCY_CREDIT_LOSS_PCT: ScenarioTargetSpec(
            target=ScenarioTarget.VACANCY_CREDIT_LOSS_PCT,
            allowed_operations=frozenset({ScenarioOperation.SET, ScenarioOperation.ADD}),
            owner_fields=MappingProxyType(
                {OperatingMode.DETAILED: "DetailedOperatingInputs.vacancy_credit_loss_pct"}
            ),
            units="decimal ratio (0.05 is 5%)",
        ),
        ScenarioTarget.EXPENSE_GROWTH: ScenarioTargetSpec(
            target=ScenarioTarget.EXPENSE_GROWTH,
            allowed_operations=frozenset({ScenarioOperation.SET, ScenarioOperation.ADD}),
            owner_fields=MappingProxyType(
                {
                    OperatingMode.DETAILED: "DetailedOperatingInputs.expense_growth",
                    OperatingMode.LEASE_LEVEL: "LeaseLevelOperatingInputs.expense_growth",
                }
            ),
            units="decimal annual rate (0.03 is 3%)",
        ),
        ScenarioTarget.MARKET_RENT_PSF: ScenarioTargetSpec(
            target=ScenarioTarget.MARKET_RENT_PSF,
            allowed_operations=frozenset(
                {
                    ScenarioOperation.SET,
                    ScenarioOperation.ADD,
                    ScenarioOperation.SCALE,
                    ScenarioOperation.CAP_AT,
                }
            ),
            owner_fields=MappingProxyType(
                {
                    OperatingMode.LEASE_LEVEL: (
                        "MarketLeasingAssumptions.market_rent_psf, resolved per suite"
                    )
                }
            ),
            units="$/SF/year as of analysis_start_date",
        ),
        ScenarioTarget.RENEWAL_PROBABILITY: ScenarioTargetSpec(
            target=ScenarioTarget.RENEWAL_PROBABILITY,
            allowed_operations=frozenset(
                {
                    ScenarioOperation.SET,
                    ScenarioOperation.ADD,
                    ScenarioOperation.SCALE,
                    ScenarioOperation.CAP_AT,
                }
            ),
            owner_fields=MappingProxyType(
                {
                    OperatingMode.LEASE_LEVEL: (
                        "MarketLeasingAssumptions.renewal_probability, property default"
                    )
                }
            ),
            units="probability (0.65 is 65%)",
        ),
        ScenarioTarget.RECOVERABLE_EXPENSE_RATIO: ScenarioTargetSpec(
            target=ScenarioTarget.RECOVERABLE_EXPENSE_RATIO,
            allowed_operations=frozenset({ScenarioOperation.SET, ScenarioOperation.ADD}),
            owner_fields=MappingProxyType(
                {
                    OperatingMode.LEASE_LEVEL: (
                        "LeaseLevelOperatingInputs.recoverable_expense_ratio"
                    )
                }
            ),
            units="decimal ratio (0.90 is 90%)",
        ),
    }
)

#: Canonical resolution order: registry declaration order (P-7). Resolution
#: never depends on the order a scenario's overrides were stored in.
_CANONICAL_ORDER: Mapping[ScenarioTarget, int] = MappingProxyType(
    {target: position for position, target in enumerate(ScenarioTarget)}
)


# =============================================================================
# The scenario contract
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioOverride:
    """One approved assumption override on one Unit (Section 7.2):
    - ``unit_id`` is the Unit (Deal) it applies to. It is required, has no
      default, and is explicit even when there is one unit;
    - ``target`` is a registry target;
    - ``operation`` is one of that target's whitelisted operations;
    - ``value`` is a finite number in the target's internal units.

    Shape only. ``validate_scenario`` holds the rules, following the
    repository's contract/validator split."""

    unit_id: str
    target: ScenarioTarget
    operation: ScenarioOperation
    value: float


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioDefinition:
    """A coherent, analyst-named view of uncertain outcomes (Section 6).

    ``scenario_id`` is a stable, opaque, nonblank identity with no financial
    meaning. ``name`` is arbitrary analyst text ("Base", "Recession 2027", ...).
    Nothing branches on it, and no count or set of scenarios is assumed.
    ``description`` is optional context. ``overrides`` holds at most one
    ``ScenarioOverride`` per ``(unit_id, target)``, and its order is
    irrelevant."""

    scenario_id: str
    name: str
    description: str | None = None
    overrides: tuple[ScenarioOverride, ...] = ()


# =============================================================================
# Deterministic issues -- the invalid-scenario contract
# =============================================================================


class ScenarioIssueStage(StrEnum):
    """Which of the two validation stages found an issue."""

    SCENARIO = "scenario"
    RESOLVED_INPUTS = "resolved_inputs"


class ScenarioIssueCode(StrEnum):
    """Stable, machine-readable reasons a scenario is invalid.

    ``UNIT_NOT_IN_VARIANT`` is SC-5: an override addresses a Unit that is not
    in the analysis. ``RESOLVED_INPUT_INVALID`` wraps an existing validator's
    finding. That issue's ``source_code`` holds the validator's own category
    or code, and its ``message`` holds the validator's own wording, so the
    business rule keeps one authority."""

    INVALID_SCENARIO_ID = "invalid_scenario_id"
    INVALID_SCENARIO_NAME = "invalid_scenario_name"
    INVALID_DESCRIPTION = "invalid_description"
    INVALID_OVERRIDES = "invalid_overrides"
    UNKNOWN_TARGET = "unknown_target"
    INVALID_UNIT_ID = "invalid_unit_id"
    DUPLICATE_TARGET = "duplicate_target"
    UNIT_NOT_IN_VARIANT = "unit_not_in_variant"
    TARGET_NOT_SUPPORTED_FOR_MODE = "target_not_supported_for_mode"
    UNKNOWN_OPERATION = "unknown_operation"
    OPERATION_NOT_ALLOWED = "operation_not_allowed"
    NON_NUMERIC_VALUE = "non_numeric_value"
    NON_FINITE_VALUE = "non_finite_value"
    TARGET_SHADOWED_BY_SUITE_OVERRIDE = "target_shadowed_by_suite_override"
    RESOLVED_INPUT_INVALID = "resolved_input_invalid"


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioIssue:
    """One deterministic reason a scenario cannot be analysed.

    This is the engine-layer invalid reason a future Strategy x Scenario cell
    displays as "invalid, with reason" (DC-2).
    - ``target`` names the override responsible, where one is.
    - ``unit_id`` names the Unit the finding concerns, where one is. For
      ``UNIT_NOT_IN_VARIANT`` that is the offending unit.
    - ``field`` locates a stage-2 finding in the resolved contracts, on the
      existing validator's own path.
    """

    stage: ScenarioIssueStage
    code: ScenarioIssueCode
    message: str
    target: ScenarioTarget | None = None
    unit_id: str | None = None
    field: str | None = None
    source_code: str | None = None

    def __str__(self) -> str:
        return self.message


class ScenarioValidationError(ValueError):
    """An invalid scenario: one ordered collection of ``ScenarioIssue``.

    Mirrors ``anchor.validation.InputValidationError``. As a ``ValueError``,
    every existing ``except ValueError`` boundary keeps working. No result is
    ever returned for an invalid scenario."""

    def __init__(self, issues: Iterable[ScenarioIssue]) -> None:
        ordered_issues = tuple(issues)
        if not ordered_issues:
            raise ValueError("ScenarioValidationError requires at least one issue.")
        if not all(isinstance(issue, ScenarioIssue) for issue in ordered_issues):
            raise TypeError("issues must contain only ScenarioIssue instances.")

        self.issues = ordered_issues
        super().__init__("\n".join(issue.message for issue in ordered_issues))


_MAX_SAFE_REPR_LENGTH = 200


def _safe_repr(value: object) -> str:
    try:
        representation = repr(value)
    except Exception:
        return f"<{type(value).__qualname__}>"
    if len(representation) > _MAX_SAFE_REPR_LENGTH:
        return f"<{type(value).__qualname__}>"
    return representation


def _scenario_issue(
    code: ScenarioIssueCode,
    message: str,
    *,
    target: ScenarioTarget | None = None,
    unit_id: str | None = None,
) -> ScenarioIssue:
    return ScenarioIssue(
        stage=ScenarioIssueStage.SCENARIO,
        code=code,
        message=message,
        target=target,
        unit_id=unit_id,
    )


# =============================================================================
# Stage 1 -- the scenario contract
# =============================================================================


def _is_nonblank_text(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _header_issues(scenario: ScenarioDefinition) -> list[ScenarioIssue]:
    """The only place a scenario's identity or naming is read. Nothing
    downstream of this function sees them, so they cannot move a number."""

    issues: list[ScenarioIssue] = []
    if not _is_nonblank_text(scenario.scenario_id):
        issues.append(
            _scenario_issue(
                ScenarioIssueCode.INVALID_SCENARIO_ID,
                f"scenario_id {_safe_repr(scenario.scenario_id)} must be a nonblank string.",
            )
        )
    if not _is_nonblank_text(scenario.name):
        issues.append(
            _scenario_issue(
                ScenarioIssueCode.INVALID_SCENARIO_NAME,
                f"name {_safe_repr(scenario.name)} must be a nonblank string.",
            )
        )
    if scenario.description is not None and not isinstance(scenario.description, str):
        issues.append(
            _scenario_issue(
                ScenarioIssueCode.INVALID_DESCRIPTION,
                f"description {_safe_repr(scenario.description)} must be a string or None.",
            )
        )
    return issues


def _value_issue(override: ScenarioOverride, unit_id: str) -> ScenarioIssue | None:
    value = override.value
    target = override.target
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return _scenario_issue(
            ScenarioIssueCode.NON_NUMERIC_VALUE,
            f"{target.value}: value {_safe_repr(value)} must be a numeric value; "
            "Booleans and text are not accepted.",
            target=target,
            unit_id=unit_id,
        )
    try:
        normalized = float(value)
    except OverflowError:
        return _scenario_issue(
            ScenarioIssueCode.NON_FINITE_VALUE,
            f"{target.value}: value {_safe_repr(value)} cannot be normalized to a "
            "finite built-in float.",
            target=target,
            unit_id=unit_id,
        )
    if not isfinite(normalized):
        return _scenario_issue(
            ScenarioIssueCode.NON_FINITE_VALUE,
            f"{target.value}: value {_safe_repr(value)} must be finite.",
            target=target,
            unit_id=unit_id,
        )
    return None


def _override_issues(
    override: ScenarioOverride, operating_mode: OperatingMode, unit_id: str
) -> list[ScenarioIssue]:
    """The per-override rules, for an override stage 1 has already proven to
    address ``unit_id`` exactly once."""

    target = override.target
    spec = SCENARIO_TARGET_REGISTRY[target]
    issues: list[ScenarioIssue] = []

    if operating_mode not in spec.modes:
        supported = ", ".join(mode.value for mode in OperatingMode if mode in spec.modes)
        issues.append(
            _scenario_issue(
                ScenarioIssueCode.TARGET_NOT_SUPPORTED_FOR_MODE,
                f"{target.value}: not a scenario target for {operating_mode.value} "
                f"underwriting; it applies to: {supported}.",
                target=target,
                unit_id=unit_id,
            )
        )

    operation = override.operation
    if not isinstance(operation, ScenarioOperation):
        issues.append(
            _scenario_issue(
                ScenarioIssueCode.UNKNOWN_OPERATION,
                f"{target.value}: unknown scenario operation {_safe_repr(operation)}.",
                target=target,
                unit_id=unit_id,
            )
        )
    elif operation not in spec.allowed_operations:
        allowed = ", ".join(
            candidate.value
            for candidate in ScenarioOperation
            if candidate in spec.allowed_operations
        )
        issues.append(
            _scenario_issue(
                ScenarioIssueCode.OPERATION_NOT_ALLOWED,
                f"{target.value}: operation {operation.value!r} is not allowed; "
                f"allowed operations: {allowed}.",
                target=target,
                unit_id=unit_id,
            )
        )

    value_issue = _value_issue(override, unit_id)
    if value_issue is not None:
        issues.append(value_issue)
    return issues


def _require_unit_identity(unit_id: object) -> None:
    """The analysed Unit's identity is the caller's fact, not scenario
    content, so a malformed one is a programming error rather than an issue."""

    if not isinstance(unit_id, str):
        raise TypeError(f"unit_id must be a str; got {type(unit_id).__qualname__}.")
    if not unit_id.strip():
        raise ValueError("unit_id must be a nonblank string naming the Unit (Deal) analysed.")


def _address_order(address: tuple[str, ScenarioTarget]) -> tuple[str, int]:
    unit, target = address
    return unit, _CANONICAL_ORDER[target]


def validate_scenario(
    scenario: ScenarioDefinition, *, operating_mode: OperatingMode, unit_id: str
) -> tuple[ScenarioIssue, ...]:
    """Stage 1: every issue in ``scenario`` as a contract for the one Unit
    ``unit_id``, analysed in ``operating_mode``. The order is deterministic
    and does not depend on how the overrides were stored:

    1. identity and naming;
    2. a malformed override collection, or malformed members of it;
    3. overrides whose target is not a ``ScenarioTarget``;
    4. overrides whose ``unit_id`` is not a nonblank string;
    5. per ``(unit_id, target)`` address, with units in sorted order and targets
       in registry order:
       - a duplicate address, reported once; its rows are never composed or
         judged individually;
       - else, an address on any unit other than ``unit_id``:
         ``UNIT_NOT_IN_VARIANT`` (SC-5). It is never ignored, filtered out or
         applied to ``unit_id``;
       - else, the target's mode applicability, then its operation, then its
         value.

    The same target on two different units is two addresses, never a
    duplicate. In P7.1, the address that is not ``unit_id`` fails
    addressability.

    Returns ``()`` for a valid scenario. Business rules on the *resolved*
    values stay with the existing validators (stage 2).
    """

    if not isinstance(scenario, ScenarioDefinition):
        raise TypeError(
            f"scenario must be a ScenarioDefinition; got {type(scenario).__qualname__}."
        )
    if not isinstance(operating_mode, OperatingMode):
        raise TypeError(
            "operating_mode must be an OperatingMode; got "
            f"{type(operating_mode).__qualname__}."
        )
    _require_unit_identity(unit_id)

    issues = _header_issues(scenario)

    overrides = scenario.overrides
    if not isinstance(overrides, tuple):
        issues.append(
            _scenario_issue(
                ScenarioIssueCode.INVALID_OVERRIDES,
                "overrides must be a tuple of ScenarioOverride; got "
                f"{type(overrides).__qualname__}.",
            )
        )
        return tuple(issues)

    for index, override in enumerate(overrides):
        if not isinstance(override, ScenarioOverride):
            issues.append(
                _scenario_issue(
                    ScenarioIssueCode.INVALID_OVERRIDES,
                    f"overrides[{index}] must be a ScenarioOverride; got "
                    f"{type(override).__qualname__}.",
                )
            )

    typed = [override for override in overrides if isinstance(override, ScenarioOverride)]
    unknown = sorted(
        (override for override in typed if not isinstance(override.target, ScenarioTarget)),
        key=lambda override: (_safe_repr(override.target), _safe_repr(override.unit_id)),
    )
    for override in unknown:
        issues.append(
            _scenario_issue(
                ScenarioIssueCode.UNKNOWN_TARGET,
                f"Unknown scenario target {_safe_repr(override.target)}; a target must "
                "be a ScenarioTarget from the approved registry.",
                unit_id=override.unit_id if _is_nonblank_text(override.unit_id) else None,
            )
        )

    targeted = [override for override in typed if isinstance(override.target, ScenarioTarget)]
    unaddressed = sorted(
        (override for override in targeted if not _is_nonblank_text(override.unit_id)),
        key=lambda override: (_CANONICAL_ORDER[override.target], _safe_repr(override.unit_id)),
    )
    for override in unaddressed:
        issues.append(
            _scenario_issue(
                ScenarioIssueCode.INVALID_UNIT_ID,
                f"{override.target.value}: unit_id {_safe_repr(override.unit_id)} must be a "
                "nonblank string naming the Unit (Deal) the override applies to.",
                target=override.target,
            )
        )

    by_address: dict[tuple[str, ScenarioTarget], list[ScenarioOverride]] = {}
    for override in targeted:
        if _is_nonblank_text(override.unit_id):
            by_address.setdefault((override.unit_id, override.target), []).append(override)

    for address in sorted(by_address, key=_address_order):
        override_unit, target = address
        occurrences = by_address[address]
        if len(occurrences) > 1:
            issues.append(
                _scenario_issue(
                    ScenarioIssueCode.DUPLICATE_TARGET,
                    f"{target.value}: {len(occurrences)} overrides target it on unit "
                    f"{_safe_repr(override_unit)}; a scenario holds at most one override "
                    "per (unit_id, target), and overrides are never composed.",
                    target=target,
                    unit_id=override_unit,
                )
            )
        elif override_unit != unit_id:
            issues.append(
                _scenario_issue(
                    ScenarioIssueCode.UNIT_NOT_IN_VARIANT,
                    f"{target.value}: the override addresses unit "
                    f"{_safe_repr(override_unit)}, which is not in this analysis; it "
                    f"resolves unit {_safe_repr(unit_id)} only. The override is refused, "
                    "never ignored and never applied to another unit.",
                    target=target,
                    unit_id=override_unit,
                )
            )
        else:
            issues.extend(_override_issues(occurrences[0], operating_mode, unit_id))

    return tuple(issues)


def _require_resolvable(
    scenario: ScenarioDefinition, operating_mode: OperatingMode, unit_id: str
) -> tuple[ScenarioOverride, ...]:
    """Raise on any stage-1 issue; otherwise return **every** override, in
    canonical registry order. Stage 1 has proven that each one addresses
    ``unit_id`` exactly once per target, so nothing is filtered here and
    nothing can be dropped."""

    issues = validate_scenario(scenario, operating_mode=operating_mode, unit_id=unit_id)
    if issues:
        raise ScenarioValidationError(issues)
    return tuple(
        sorted(scenario.overrides, key=lambda override: _CANONICAL_ORDER[override.target])
    )


def _lease_level_applicability_issues(
    overrides: tuple[ScenarioOverride, ...], suites: tuple[Suite, ...], unit_id: str
) -> tuple[ScenarioIssue, ...]:
    """Stage 1, against the inputs: a target these suites shadow is refused.

    ``renewal_probability`` is a property-default target. A suite with a full
    ``market_leasing_override`` takes its renewal probability from that record
    alone (D0 Section 24.2). Applying the scenario to the default would
    therefore silently skip that suite. Q10 ratified a unit-wide reach for
    market rent only, so for renewal probability the scenario is refused
    rather than partly applied (the D4.6B shadowing rule, failing closed). A
    suite carrying only the scalar ``market_rent_psf`` does not shadow it.
    """

    if not any(override.target is ScenarioTarget.RENEWAL_PROBABILITY for override in overrides):
        return ()
    shadowing = tuple(
        suite.suite_id for suite in suites if suite.market_leasing_override is not None
    )
    if not shadowing:
        return ()
    return (
        _scenario_issue(
            ScenarioIssueCode.TARGET_SHADOWED_BY_SUITE_OVERRIDE,
            "renewal_probability: suite(s) "
            f"{', '.join(shadowing)} carry a full market_leasing_override that shadows "
            "the property-default renewal probability, so this scenario would not "
            "reach them. It is refused rather than partly applied.",
            target=ScenarioTarget.RENEWAL_PROBABILITY,
            unit_id=unit_id,
        ),
    )


# =============================================================================
# Resolved inputs -- existing contracts, nothing else
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedQuickInputs:
    """Exactly what a Quick analysis of this scenario runs: the ordinary
    contracts, with the Business Plan carried through unchanged (P7.1 changes
    no plan)."""

    inputs: AcquisitionInputs
    business_plan: BusinessPlan


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedDetailedInputs:
    """Exactly what a Detailed analysis of this scenario runs."""

    terms: AcquisitionTerms
    detailed_operating_inputs: DetailedOperatingInputs
    business_plan: BusinessPlan


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedLeaseLevelInputs:
    """Exactly what a Lease-Level analysis of this scenario runs."""

    terms: AcquisitionTerms
    property_inputs: LeaseLevelPropertyInputs
    suites: tuple[Suite, ...]
    leases: tuple[Lease, ...]
    market_leasing: MarketLeasingAssumptions
    operating_inputs: LeaseLevelOperatingInputs
    business_plan: BusinessPlan


# =============================================================================
# Resolution -- one explicit, typed resolver per (target, mode)
# =============================================================================


def _resolved_value(override: ScenarioOverride, current: float) -> float:
    return _apply_operation(override.operation, current, override.value)


def _no_resolver(target: object, operating_mode: OperatingMode) -> ValueError:
    return ValueError(
        f"No {operating_mode.value} resolver exists for scenario target "
        f"{_safe_repr(target)}."
    )


def _resolve_quick_target(
    inputs: AcquisitionInputs, override: ScenarioOverride
) -> AcquisitionInputs:
    match override.target:
        case ScenarioTarget.EXIT_CAP_RATE:
            return replace(
                inputs, exit_cap_rate=_resolved_value(override, inputs.exit_cap_rate)
            )
        case ScenarioTarget.INTEREST_RATE:
            return replace(
                inputs, interest_rate=_resolved_value(override, inputs.interest_rate)
            )
        case ScenarioTarget.LTV:
            return replace(inputs, ltv=_resolved_value(override, inputs.ltv))
        case ScenarioTarget.NOI_GROWTH:
            return replace(inputs, noi_growth=_resolved_value(override, inputs.noi_growth))
        case _:
            raise _no_resolver(override.target, OperatingMode.QUICK)


def _resolve_terms_target(
    terms: AcquisitionTerms, override: ScenarioOverride
) -> AcquisitionTerms:
    """The ``AcquisitionTerms`` targets, which Detailed and Lease-Level
    share."""

    match override.target:
        case ScenarioTarget.EXIT_CAP_RATE:
            return replace(terms, exit_cap_rate=_resolved_value(override, terms.exit_cap_rate))
        case ScenarioTarget.INTEREST_RATE:
            return replace(terms, interest_rate=_resolved_value(override, terms.interest_rate))
        case ScenarioTarget.LTV:
            return replace(terms, ltv=_resolved_value(override, terms.ltv))
        case _:
            raise ValueError(
                f"{_safe_repr(override.target)} is not an AcquisitionTerms scenario target."
            )


def _resolve_detailed_target(
    resolved: ResolvedDetailedInputs, override: ScenarioOverride
) -> ResolvedDetailedInputs:
    operating = resolved.detailed_operating_inputs
    match override.target:
        case ScenarioTarget.EXIT_CAP_RATE | ScenarioTarget.INTEREST_RATE | ScenarioTarget.LTV:
            return replace(resolved, terms=_resolve_terms_target(resolved.terms, override))
        case ScenarioTarget.REVENUE_GROWTH:
            return replace(
                resolved,
                detailed_operating_inputs=replace(
                    operating,
                    revenue_growth=_resolved_value(override, operating.revenue_growth),
                ),
            )
        case ScenarioTarget.VACANCY_CREDIT_LOSS_PCT:
            return replace(
                resolved,
                detailed_operating_inputs=replace(
                    operating,
                    vacancy_credit_loss_pct=_resolved_value(
                        override, operating.vacancy_credit_loss_pct
                    ),
                ),
            )
        case ScenarioTarget.EXPENSE_GROWTH:
            return replace(
                resolved,
                detailed_operating_inputs=replace(
                    operating,
                    expense_growth=_resolved_value(override, operating.expense_growth),
                ),
            )
        case _:
            raise _no_resolver(override.target, OperatingMode.DETAILED)


def _with_market_rent(
    assumptions: MarketLeasingAssumptions, override: ScenarioOverride
) -> MarketLeasingAssumptions:
    return replace(
        assumptions,
        market_rent_psf=_resolved_value(override, assumptions.market_rent_psf),
    )


def _suite_with_market_rent(suite: Suite, override: ScenarioOverride) -> Suite:
    """Move every market-rent level this suite states.

    Under Q10, as ratified for P7.1, ``market_rent_psf`` is a **unit-wide**
    target over resolved suite market rents, and an explicit suite override
    does not shield a suite from it. A suite's resolved rent is whichever of
    these wins under the one precedence rule, ``leasing.market.
    resolve_market_leasing`` (D0 Section 24.1):
    - its scalar ``market_rent_psf``;
    - else its full override's ``market_rent_psf``;
    - else the property default.

    The operation is applied to *each* level the configuration states: here,
    and to the property default in ``_resolve_lease_level_target``. Each
    operation is a function of one value, so the level that wins after
    resolution is the operation applied to the level that won before. SET,
    ADD, SCALE and CAP_AT therefore all act on every suite's resolved rent,
    including explicit overrides, while every precedence source and provenance
    flag stays where the analyst put it.

    A level that no suite resolves to moves too. The configuration stays one
    coherent market, and every declared record stays subject to the existing
    validator (the D4.5B rule that an override is a declared input whether or
    not a roll resolves to it). The explicit renewal level
    ``renewal_rent_psf`` is a negotiated rent, not market rent, and is never
    touched.
    """

    if suite.market_rent_psf is None and suite.market_leasing_override is None:
        return suite
    return replace(
        suite,
        market_rent_psf=(
            None
            if suite.market_rent_psf is None
            else _resolved_value(override, suite.market_rent_psf)
        ),
        market_leasing_override=(
            None
            if suite.market_leasing_override is None
            else _with_market_rent(suite.market_leasing_override, override)
        ),
    )


def _resolve_lease_level_target(
    resolved: ResolvedLeaseLevelInputs, override: ScenarioOverride
) -> ResolvedLeaseLevelInputs:
    market = resolved.market_leasing
    operating = resolved.operating_inputs
    match override.target:
        case ScenarioTarget.EXIT_CAP_RATE | ScenarioTarget.INTEREST_RATE | ScenarioTarget.LTV:
            return replace(resolved, terms=_resolve_terms_target(resolved.terms, override))
        case ScenarioTarget.MARKET_RENT_PSF:
            return replace(
                resolved,
                market_leasing=_with_market_rent(market, override),
                suites=tuple(
                    _suite_with_market_rent(suite, override) for suite in resolved.suites
                ),
            )
        case ScenarioTarget.RENEWAL_PROBABILITY:
            return replace(
                resolved,
                market_leasing=replace(
                    market,
                    renewal_probability=_resolved_value(override, market.renewal_probability),
                ),
            )
        case ScenarioTarget.EXPENSE_GROWTH:
            return replace(
                resolved,
                operating_inputs=replace(
                    operating,
                    expense_growth=_resolved_value(override, operating.expense_growth),
                ),
            )
        case ScenarioTarget.RECOVERABLE_EXPENSE_RATIO:
            return replace(
                resolved,
                operating_inputs=replace(
                    operating,
                    recoverable_expense_ratio=_resolved_value(
                        override, operating.recoverable_expense_ratio
                    ),
                ),
            )
        case _:
            raise _no_resolver(override.target, OperatingMode.LEASE_LEVEL)


# =============================================================================
# Stage 2 -- the existing validators, on every contract a target changed
# =============================================================================


def _applied_targets(
    overrides: tuple[ScenarioOverride, ...],
) -> Mapping[str, ScenarioTarget]:
    return {override.target.value: override.target for override in overrides}


def _resolved_input_issue(
    *,
    message: str,
    field: str | None,
    source_code: str,
    applied: Mapping[str, ScenarioTarget],
    unit_id: str,
) -> ScenarioIssue:
    """Wrap one existing finding, unchanged. Every stage-2 finding concerns
    the one Unit being resolved. Each target token is its field's own name, so
    a finding on a field a target wrote is attributed to that target. Any
    other finding (a pre-existing defect in the base inputs) is reported with
    no target."""

    leaf = None if field is None else field.rpartition(".")[2]
    return ScenarioIssue(
        stage=ScenarioIssueStage.RESOLVED_INPUTS,
        code=ScenarioIssueCode.RESOLVED_INPUT_INVALID,
        message=message,
        target=None if leaf is None else applied.get(leaf),
        unit_id=unit_id,
        field=field,
        source_code=source_code,
    )


def _input_error_issues(
    error: InputValidationError, applied: Mapping[str, ScenarioTarget], unit_id: str
) -> list[ScenarioIssue]:
    return [
        _resolved_input_issue(
            message=issue.message,
            field=issue.field_id,
            source_code=issue.category.value,
            applied=applied,
            unit_id=unit_id,
        )
        for issue in error.issues
    ]


def _lease_error_issues(
    errors: Iterable[LeaseValidationIssue],
    applied: Mapping[str, ScenarioTarget],
    unit_id: str,
) -> list[ScenarioIssue]:
    return [
        _resolved_input_issue(
            message=issue.message,
            field=issue.path,
            source_code=issue.code.value,
            applied=applied,
            unit_id=unit_id,
        )
        for issue in errors
    ]


def _quick_input_issues(
    inputs: AcquisitionInputs, applied: Mapping[str, ScenarioTarget], unit_id: str
) -> list[ScenarioIssue]:
    try:
        validate_acquisition_inputs(asdict(inputs))
    except InputValidationError as error:
        return _input_error_issues(error, applied, unit_id)
    return []


def _terms_issues(
    terms: AcquisitionTerms, applied: Mapping[str, ScenarioTarget], unit_id: str
) -> list[ScenarioIssue]:
    try:
        validate_acquisition_terms(asdict(terms))
    except InputValidationError as error:
        return _input_error_issues(error, applied, unit_id)
    return []


def _detailed_operating_issues(
    operating: DetailedOperatingInputs, applied: Mapping[str, ScenarioTarget], unit_id: str
) -> list[ScenarioIssue]:
    try:
        validate_detailed_operating_inputs(asdict(operating))
    except InputValidationError as error:
        return _input_error_issues(error, applied, unit_id)
    return []


def _require_no_issues(issues: list[ScenarioIssue]) -> None:
    if issues:
        raise ScenarioValidationError(issues)


def _require_instance(value: object, expected: type, name: str) -> None:
    if not isinstance(value, expected):
        raise TypeError(
            f"{name} must be {expected.__qualname__}; got {type(value).__qualname__}."
        )


# =============================================================================
# Public resolvers -- one Unit per call
# =============================================================================


def resolve_quick_scenario(
    inputs: AcquisitionInputs,
    *,
    unit_id: str,
    scenario: ScenarioDefinition,
    business_plan: BusinessPlan,
) -> ResolvedQuickInputs:
    """Resolve ``scenario`` over the Quick inputs of the Unit ``unit_id``.

    Every override must address ``unit_id``. Any other unit makes the
    scenario invalid rather than being ignored.

    Raises ``ScenarioValidationError`` with stage-1 issues, or else with the
    existing validator's stage-2 findings on the resolved ``AcquisitionInputs``.
    The resolved value is always the candidate itself: validation is a gate,
    never a transform, and it clips nothing. ``inputs`` and ``business_plan``
    are never mutated, and with no overrides the caller's own objects come
    back."""

    _require_instance(inputs, AcquisitionInputs, "inputs")
    _require_instance(business_plan, BusinessPlan, "business_plan")
    overrides = _require_resolvable(scenario, OperatingMode.QUICK, unit_id)

    resolved = inputs
    for override in overrides:
        resolved = _resolve_quick_target(resolved, override)
    if overrides:
        _require_no_issues(
            _quick_input_issues(resolved, _applied_targets(overrides), unit_id)
        )

    return ResolvedQuickInputs(inputs=resolved, business_plan=business_plan)


def resolve_detailed_scenario(
    terms: AcquisitionTerms,
    detailed_operating_inputs: DetailedOperatingInputs,
    *,
    unit_id: str,
    scenario: ScenarioDefinition,
    business_plan: BusinessPlan,
) -> ResolvedDetailedInputs:
    """Resolve ``scenario`` over the Detailed terms and operating inputs of
    the Unit ``unit_id``.

    Stage 2 validates each contract a target changed, terms first, with the
    same validators the Detailed API path uses. A contract no target changed
    is passed through as the caller's own object."""

    _require_instance(terms, AcquisitionTerms, "terms")
    _require_instance(
        detailed_operating_inputs, DetailedOperatingInputs, "detailed_operating_inputs"
    )
    _require_instance(business_plan, BusinessPlan, "business_plan")
    overrides = _require_resolvable(scenario, OperatingMode.DETAILED, unit_id)

    base = ResolvedDetailedInputs(
        terms=terms,
        detailed_operating_inputs=detailed_operating_inputs,
        business_plan=business_plan,
    )
    resolved = base
    for override in overrides:
        resolved = _resolve_detailed_target(resolved, override)

    applied = _applied_targets(overrides)
    issues: list[ScenarioIssue] = []
    if resolved.terms is not base.terms:
        issues.extend(_terms_issues(resolved.terms, applied, unit_id))
    if resolved.detailed_operating_inputs is not base.detailed_operating_inputs:
        issues.extend(
            _detailed_operating_issues(resolved.detailed_operating_inputs, applied, unit_id)
        )
    _require_no_issues(issues)
    return resolved


def resolve_lease_level_scenario(
    terms: AcquisitionTerms,
    property_inputs: LeaseLevelPropertyInputs,
    suites: Iterable[Suite],
    leases: Iterable[Lease],
    *,
    market_leasing: MarketLeasingAssumptions,
    operating_inputs: LeaseLevelOperatingInputs,
    unit_id: str,
    scenario: ScenarioDefinition,
    business_plan: BusinessPlan,
) -> ResolvedLeaseLevelInputs:
    """Resolve ``scenario`` over the Lease-Level inputs of the Unit
    ``unit_id``.

    The suites and the property-default market record come back as a **new**
    resolved configuration, and the caller's records are never mutated. Stage 2
    validates, in the pipeline's own order:
    - the terms, if a target changed them;
    - the rent roll with its market records, through the D1/D2 leasing
      validator, if a market target changed them;
    - the property operating inputs, if a target changed them.

    Warnings, such as the weighted-rollover notice, never make a scenario
    invalid.

    Downstream conditions that only the full analysis can meet stay with the
    analysis. One example is the positive forward exit NOI (HD-D4-7). Those
    raise from it exactly as they would for the same inputs entered by hand.
    """

    _require_instance(terms, AcquisitionTerms, "terms")
    _require_instance(property_inputs, LeaseLevelPropertyInputs, "property_inputs")
    _require_instance(market_leasing, MarketLeasingAssumptions, "market_leasing")
    _require_instance(operating_inputs, LeaseLevelOperatingInputs, "operating_inputs")
    _require_instance(business_plan, BusinessPlan, "business_plan")
    suite_tuple = tuple(suites)
    lease_tuple = tuple(leases)

    overrides = _require_resolvable(scenario, OperatingMode.LEASE_LEVEL, unit_id)
    shadowed = _lease_level_applicability_issues(overrides, suite_tuple, unit_id)
    if shadowed:
        raise ScenarioValidationError(shadowed)

    base = ResolvedLeaseLevelInputs(
        terms=terms,
        property_inputs=property_inputs,
        suites=suite_tuple,
        leases=lease_tuple,
        market_leasing=market_leasing,
        operating_inputs=operating_inputs,
        business_plan=business_plan,
    )
    resolved = base
    for override in overrides:
        resolved = _resolve_lease_level_target(resolved, override)

    applied = _applied_targets(overrides)
    issues: list[ScenarioIssue] = []
    if resolved.terms is not base.terms:
        issues.extend(_terms_issues(resolved.terms, applied, unit_id))
    if resolved.market_leasing is not base.market_leasing or resolved.suites is not base.suites:
        issues.extend(
            _lease_error_issues(
                validate_lease_level_inputs(
                    resolved.property_inputs,
                    resolved.suites,
                    resolved.leases,
                    hold_period=resolved.terms.hold_period,
                    market_leasing=resolved.market_leasing,
                ).errors,
                applied,
                unit_id,
            )
        )
    if resolved.operating_inputs is not base.operating_inputs:
        issues.extend(
            _lease_error_issues(
                validate_lease_level_operating_inputs(resolved.operating_inputs).errors,
                applied,
                unit_id,
            )
        )
    _require_no_issues(issues)
    return resolved


# =============================================================================
# Analysis -- the existing entry points on resolved inputs
# =============================================================================


def analyze_quick_acquisition_with_scenario(
    inputs: AcquisitionInputs,
    *,
    unit_id: str,
    scenario: ScenarioDefinition,
    business_plan: BusinessPlan,
) -> AcquisitionResults:
    """Resolve ``scenario`` for the Unit ``unit_id``, then run the existing
    Quick Business Plan entry point on the resolved contracts. There is no
    scenario-specific financial code path (SC-7). The result is identical to
    entering the resolved assumptions by hand."""

    resolved = resolve_quick_scenario(
        inputs, unit_id=unit_id, scenario=scenario, business_plan=business_plan
    )
    return analyze_quick_acquisition_with_business_plan(
        resolved.inputs, business_plan=resolved.business_plan
    )


def analyze_detailed_acquisition_with_scenario(
    terms: AcquisitionTerms,
    detailed_operating_inputs: DetailedOperatingInputs,
    *,
    unit_id: str,
    scenario: ScenarioDefinition,
    business_plan: BusinessPlan,
) -> DetailedAcquisitionResults:
    """Resolve ``scenario`` for the Unit ``unit_id``, then run the existing
    Detailed Business Plan entry point on the resolved contracts."""

    resolved = resolve_detailed_scenario(
        terms,
        detailed_operating_inputs,
        unit_id=unit_id,
        scenario=scenario,
        business_plan=business_plan,
    )
    return analyze_detailed_acquisition_with_business_plan(
        resolved.terms,
        resolved.detailed_operating_inputs,
        business_plan=resolved.business_plan,
    )


def analyze_lease_level_acquisition_with_scenario(
    terms: AcquisitionTerms,
    property_inputs: LeaseLevelPropertyInputs,
    suites: Iterable[Suite],
    leases: Iterable[Lease],
    *,
    market_leasing: MarketLeasingAssumptions,
    operating_inputs: LeaseLevelOperatingInputs,
    unit_id: str,
    scenario: ScenarioDefinition,
    business_plan: BusinessPlan,
) -> LeaseLevelAcquisitionResults:
    """Resolve ``scenario`` for the Unit ``unit_id``, then run the existing
    Lease-Level Business Plan entry point on the resolved contracts."""

    resolved = resolve_lease_level_scenario(
        terms,
        property_inputs,
        suites,
        leases,
        market_leasing=market_leasing,
        operating_inputs=operating_inputs,
        unit_id=unit_id,
        scenario=scenario,
        business_plan=business_plan,
    )
    return analyze_lease_level_acquisition_with_business_plan(
        resolved.terms,
        resolved.property_inputs,
        resolved.suites,
        resolved.leases,
        market_leasing=resolved.market_leasing,
        operating_inputs=resolved.operating_inputs,
        business_plan=resolved.business_plan,
    )
