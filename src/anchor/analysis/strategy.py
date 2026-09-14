"""Phase 7 Gate P7.4 -- the Strategy engine.

Restates ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections
7.1, 7.4 and 7.6, and its Section 21 record (Q16, Q24); that document governs on
any discrepancy. P7.4 carries the one Q16 engine-scope approval for this gate:
Strategy resolution into the existing contracts, composed with the existing
P7.1 Scenario resolution, analysed through the existing D6 entry points. No
formula, engine contract, Scenario semantic or Business Plan convention moves.

**A Strategy is what the analyst or investor chooses**: a bid, a financing
package, a Business Plan, the operating outcome the analyst underwrites for that
plan, a hold. A Scenario (``anchor.analysis.scenario``) is what the analyst
assumes may happen to that choice. They stay two concepts and two contracts.

**Resolve, then run (P-2), in the one permanent order (ST-3)**::

    the Unit's Base inputs                  the Deal as stored, never mutated
            |
    Strategy          stage 1: the strategy contract -- identity, unit
            |         addressing, domains, whole-domain completeness, numbers
            |         and the operating-outcome whitelist; then each overlay,
            |         in domain declaration order
    Scenario          the unchanged P7.1 resolver, run on the Strategy-resolved
            |         contracts, so a relative operation acts on the value the
            |         Strategy chose and never on Base's (SC-3)
    validation        the existing validators, on every final contract that is
            |         not the Deal's own object
    Resolved*Inputs   the P7.1 bundles: existing input contracts only
            |
    analyze_*_acquisition_with_business_plan     the existing D6 entry points

Both layers are gone before the engine boundary. Nothing here computes NOI,
debt service, a value or a return, and this module has no arithmetic at all: a
Strategy only ever *states* a value.

**Five domains, each a whole-domain overlay (ST-2)**, and one home per field:

- ``ACQUISITION``: ``purchase_price`` and ``acquisition_cost_pct``;
- ``FINANCING``: the acquisition loan -- ``ltv``, ``interest_rate``,
  ``amortization``, ``io_period`` and ``financing_fee_pct``;
- ``BUSINESS_PLAN``: a whole D6 ``BusinessPlan``, which replaces the Deal's.
  The empty plan is a real choice ("this strategy executes no Business Plan"),
  distinct from having no overlay at all;
- ``OPERATING_OUTCOME``: explicit ``SET`` values over approved Scenario Target
  Registry tokens (``STRATEGY_OUTCOME_TARGETS``);
- ``DISPOSITION``: ``hold_period``.

A whole-domain overlay states every field of its domain. An omitted field is an
incomplete overlay and is refused; it is never inherited from Base.

**Operating outcomes are explicit assumptions (Q24, ST-6, P-13).** An outcome is
what the analyst chose to underwrite for the strategy, typed in. Nothing here
derives one from a Business Plan, or from anything else: the Business Plan is
carried whole and never opened, and the outcome path never sees it. Removing
either overlay leaves the other exactly as it was.

**The P7.1 target resolvers are reused.** An outcome is applied through the
P7.1 per-target resolver of its mode with the ``SET`` operation, so it reaches
exactly the field -- and, for Lease-Level market rent, exactly the suite levels
-- a Scenario ``SET`` reaches, and no field accessor is restated here. The P7.1
*public* resolvers are not used for this step because they validate what they
change, and a Strategy-resolved value is intermediate: only the final inputs are
validated.

**Two layers of validity.** ``validate_strategy`` is the strategy contract: what
may be stored. It never asks whether the strategy produces valid underwriting,
because the Base inputs and the Scenario can change afterwards. Whether a
variant resolves to valid inputs is decided at resolution, by the existing
validators, and an invalid variant is refused with their reason (SC-4). Nothing
is clipped.

**UNIT_SELECTION does not ship in P7.4** (the Section 21.3 question P7.4
settles). Multi-unit Investments and consolidation belong to P7.6, and an
alternate Unit held for one strategy would need both. A strategy that needs a
different rent roll, operating mode or structural Unit is therefore not
expressible yet. No Deal is duplicated to fake one.

**Names are not financial (FP-1).** ``strategy_id``, ``name`` and
``description`` are read by the stage-1 header check alone.

**Deliberately not here**: persistence, fingerprints, the cache and the routes
(``anchor.deals``, ``anchor.api``); comparison (P7.5); multi-unit resolution
(P7.6); capital structure (P7.7, P7.8); partnership (P7.9).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from math import isfinite
from types import MappingProxyType
from typing import TypeVar

from ..business_plan import BusinessPlan, validate_business_plan
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
from .scenario import (
    ResolvedDetailedInputs,
    ResolvedLeaseLevelInputs,
    ResolvedQuickInputs,
    ScenarioDefinition,
    ScenarioOperation,
    ScenarioOverride,
    ScenarioTarget,
    _is_nonblank_text,
    _require_instance,
    _require_unit_identity,
    _resolve_detailed_target,
    _resolve_lease_level_target,
    _resolve_quick_target,
    _safe_repr,
    resolve_detailed_scenario,
    resolve_lease_level_scenario,
    resolve_quick_scenario,
)

# =============================================================================
# The variant identity's reserved keys
# =============================================================================

#: The implicit Base Strategy (Section 15.1): the Deal's own stored inputs. It is
#: never a stored Strategy, and no Strategy may take this id.
BASE_STRATEGY_ID = "base"

#: The implicit Base Scenario in a variant identity (Section 7.5): no scenario
#: at all. A persisted Scenario with no overrides is a Scenario, never this key.
BASE_SCENARIO_ID = "base"


# =============================================================================
# Domains and the one home of every field
# =============================================================================


class StrategyDomain(StrEnum):
    """The five P7.4 Strategy domains. Declaration order is the canonical order
    for resolution and for reporting.

    Section 7.4 also names ``CAPITAL_STRUCTURE``, ``PARTNERSHIP`` and
    ``UNIT_SELECTION``. They belong to later gates and are deliberately not
    members, so a token naming one is refused (``UNSUPPORTED_DOMAIN``)."""

    ACQUISITION = "acquisition"
    FINANCING = "financing"
    BUSINESS_PLAN = "business_plan"
    OPERATING_OUTCOME = "operating_outcome"
    DISPOSITION = "disposition"


_DOMAIN_RANK: Mapping[StrategyDomain, int] = MappingProxyType(
    {domain: rank for rank, domain in enumerate(StrategyDomain)}
)

#: Every input field a Strategy can write, under the one domain that owns it. No
#: field has two homes. ``interest_rate`` and ``ltv`` are financing decisions,
#: so they are FINANCING fields and never operating outcomes; ``exit_cap_rate``
#: is an operating outcome and never DISPOSITION.
STRATEGY_DOMAIN_FIELDS: Mapping[StrategyDomain, tuple[str, ...]] = MappingProxyType(
    {
        StrategyDomain.ACQUISITION: ("purchase_price", "acquisition_cost_pct"),
        StrategyDomain.FINANCING: (
            "ltv",
            "interest_rate",
            "amortization",
            "io_period",
            "financing_fee_pct",
        ),
        StrategyDomain.BUSINESS_PLAN: ("business_plan",),
        StrategyDomain.OPERATING_OUTCOME: (
            "exit_cap_rate",
            "noi_growth",
            "revenue_growth",
            "vacancy_credit_loss_pct",
            "expense_growth",
            "market_rent_psf",
            "renewal_probability",
            "recoverable_expense_ratio",
        ),
        StrategyDomain.DISPOSITION: ("hold_period",),
    }
)

#: The Strategy whitelist over the P7.1 Scenario Target Registry: which tokens
#: an operating outcome may ``SET`` in each mode, in registry order. Every one
#: is a registry target for that mode, so its resolver already exists. This is
#: a whitelist of registry tokens, not a second registry.
STRATEGY_OUTCOME_TARGETS: Mapping[OperatingMode, tuple[ScenarioTarget, ...]] = MappingProxyType(
    {
        OperatingMode.QUICK: (ScenarioTarget.EXIT_CAP_RATE, ScenarioTarget.NOI_GROWTH),
        OperatingMode.DETAILED: (
            ScenarioTarget.EXIT_CAP_RATE,
            ScenarioTarget.REVENUE_GROWTH,
            ScenarioTarget.VACANCY_CREDIT_LOSS_PCT,
            ScenarioTarget.EXPENSE_GROWTH,
        ),
        OperatingMode.LEASE_LEVEL: (
            ScenarioTarget.EXIT_CAP_RATE,
            ScenarioTarget.EXPENSE_GROWTH,
            ScenarioTarget.MARKET_RENT_PSF,
            ScenarioTarget.RENEWAL_PROBABILITY,
            ScenarioTarget.RECOVERABLE_EXPENSE_RATIO,
        ),
    }
)

_TARGET_RANK: Mapping[ScenarioTarget, int] = MappingProxyType(
    {target: rank for rank, target in enumerate(ScenarioTarget)}
)


# =============================================================================
# The strategy contract
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionChoice:
    """The ACQUISITION domain, whole: the price and acquisition-cost package
    chosen. A bid is always a Strategy, never a Scenario."""

    purchase_price: float
    acquisition_cost_pct: float


@dataclass(frozen=True, slots=True, kw_only=True)
class FinancingChoice:
    """The FINANCING domain, whole: the acquisition loan chosen. It resolves
    into the existing loan fields and the existing debt engine sizes it."""

    ltv: float
    interest_rate: float
    amortization: int
    io_period: int
    financing_fee_pct: float


@dataclass(frozen=True, slots=True, kw_only=True)
class OperatingOutcome:
    """One operating assumption the strategy underwrites: a registry token, the
    ``SET`` operation (the only one a Strategy has) and a finite value in the
    target's internal units."""

    target: ScenarioTarget
    operation: ScenarioOperation
    value: float


@dataclass(frozen=True, slots=True, kw_only=True)
class OperatingOutcomeSet:
    """The OPERATING_OUTCOME domain: at least one outcome, at most one per
    target. Order carries no meaning."""

    outcomes: tuple[OperatingOutcome, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class DispositionChoice:
    """The DISPOSITION domain, whole: the hold chosen. Strategies with different
    holds are legitimate, and nothing here aligns their years (ST-5)."""

    hold_period: int


#: What an overlay carries, by domain. BUSINESS_PLAN carries the D6
#: ``BusinessPlan`` itself -- the same contract, never a parallel one.
StrategyOverlayContent = (
    AcquisitionChoice | FinancingChoice | BusinessPlan | OperatingOutcomeSet | DispositionChoice
)

_CONTENT_TYPES: Mapping[StrategyDomain, type] = MappingProxyType(
    {
        StrategyDomain.ACQUISITION: AcquisitionChoice,
        StrategyDomain.FINANCING: FinancingChoice,
        StrategyDomain.BUSINESS_PLAN: BusinessPlan,
        StrategyDomain.OPERATING_OUTCOME: OperatingOutcomeSet,
        StrategyDomain.DISPOSITION: DispositionChoice,
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyOverlay:
    """One domain overlay on one Unit: ``unit_id`` is the Unit (Deal) it
    applies to, explicit even with one unit; ``content`` is that domain's
    contract. Shape only: ``validate_strategy`` holds the rules."""

    unit_id: str
    domain: StrategyDomain
    content: StrategyOverlayContent


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyDefinition:
    """A named decision configuration (Section 6).

    ``strategy_id`` is a stable, opaque, nonblank identity other than the
    reserved Base key. ``name`` is arbitrary analyst text and ``description``
    optional context; neither has financial meaning. ``overlays`` holds at most
    one overlay per ``(domain, unit_id)``, and its order is irrelevant."""

    strategy_id: str
    name: str
    description: str | None = None
    overlays: tuple[StrategyOverlay, ...] = ()


# =============================================================================
# Deterministic issues -- the invalid-strategy contract
# =============================================================================


class StrategyIssueStage(StrEnum):
    """Which layer found an issue: the strategy contract, or the variant's
    resolved inputs."""

    STRATEGY = "strategy"
    RESOLVED_INPUTS = "resolved_inputs"


class StrategyIssueCode(StrEnum):
    """Stable, machine-readable reasons a strategy or its variant is invalid.

    ``RESOLVED_INPUT_INVALID`` wraps an existing validator's finding on the
    final inputs; ``source_code`` holds the validator's own code and
    ``message`` its own wording, so the business rule keeps one authority."""

    INVALID_STRATEGY_ID = "invalid_strategy_id"
    RESERVED_STRATEGY_ID = "reserved_strategy_id"
    INVALID_NAME = "invalid_name"
    INVALID_DESCRIPTION = "invalid_description"
    INVALID_OVERLAYS = "invalid_overlays"
    UNSUPPORTED_DOMAIN = "unsupported_domain"
    INVALID_UNIT_ID = "invalid_unit_id"
    DUPLICATE_DOMAIN = "duplicate_domain"
    UNIT_NOT_IN_VARIANT = "unit_not_in_variant"
    INVALID_CONTENT = "invalid_content"
    INCOMPLETE_DOMAIN = "incomplete_domain"
    INVALID_NUMBER = "invalid_number"
    INVALID_BUSINESS_PLAN = "invalid_business_plan"
    UNSUPPORTED_TARGET = "unsupported_target"
    DUPLICATE_TARGET = "duplicate_target"
    INVALID_OPERATION = "invalid_operation"
    TARGET_SHADOWED_BY_SUITE_OVERRIDE = "target_shadowed_by_suite_override"
    RESOLVED_INPUT_INVALID = "resolved_input_invalid"


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyIssue:
    """One deterministic reason a strategy, or a variant of it, cannot be
    analysed. ``domain``, ``unit_id`` and ``target`` name what is responsible
    where something is; ``field`` locates the finding; ``source_code`` is an
    existing validator's own code."""

    stage: StrategyIssueStage
    code: StrategyIssueCode
    message: str
    domain: StrategyDomain | None = None
    unit_id: str | None = None
    field: str | None = None
    target: ScenarioTarget | None = None
    source_code: str | None = None

    def __str__(self) -> str:
        return self.message


class StrategyValidationError(ValueError):
    """An invalid strategy or variant: one ordered collection of
    ``StrategyIssue``. Mirrors ``ScenarioValidationError``. No result is ever
    returned for an invalid strategy."""

    def __init__(self, issues: Iterable[StrategyIssue]) -> None:
        ordered_issues = tuple(issues)
        if not ordered_issues:
            raise ValueError("StrategyValidationError requires at least one issue.")
        if not all(isinstance(issue, StrategyIssue) for issue in ordered_issues):
            raise TypeError("issues must contain only StrategyIssue instances.")

        self.issues = ordered_issues
        super().__init__("\n".join(issue.message for issue in ordered_issues))


def _strategy_issue(
    code: StrategyIssueCode,
    message: str,
    *,
    domain: StrategyDomain | None = None,
    unit_id: str | None = None,
    field: str | None = None,
    target: ScenarioTarget | None = None,
    source_code: str | None = None,
) -> StrategyIssue:
    return StrategyIssue(
        stage=StrategyIssueStage.STRATEGY,
        code=code,
        message=message,
        domain=domain,
        unit_id=unit_id,
        field=field,
        target=target,
        source_code=source_code,
    )


# =============================================================================
# Stage 1 -- the strategy contract
# =============================================================================


def _header_issues(strategy: StrategyDefinition) -> list[StrategyIssue]:
    """The only place a strategy's identity or naming is read. Nothing
    downstream of this function sees them, so they cannot move a number."""

    issues: list[StrategyIssue] = []
    strategy_id = strategy.strategy_id
    if not _is_nonblank_text(strategy_id):
        issues.append(
            _strategy_issue(
                StrategyIssueCode.INVALID_STRATEGY_ID,
                f"strategy_id {_safe_repr(strategy_id)} must be a nonblank string.",
            )
        )
    elif strategy_id.strip().casefold() == BASE_STRATEGY_ID:
        issues.append(
            _strategy_issue(
                StrategyIssueCode.RESERVED_STRATEGY_ID,
                f"strategy_id {_safe_repr(strategy_id)} is reserved for the implicit Base "
                "strategy, which is the Deal's own inputs and is never stored.",
            )
        )
    if not _is_nonblank_text(strategy.name):
        issues.append(
            _strategy_issue(
                StrategyIssueCode.INVALID_NAME,
                f"name {_safe_repr(strategy.name)} must be a nonblank string.",
            )
        )
    if strategy.description is not None and not isinstance(strategy.description, str):
        issues.append(
            _strategy_issue(
                StrategyIssueCode.INVALID_DESCRIPTION,
                f"description {_safe_repr(strategy.description)} must be a string or None.",
            )
        )
    return issues


def _value_problem(value: object, *, whole: bool) -> str | None:
    """Why ``value`` is not a usable number, or ``None``. Finite numbers only;
    a whole-number field takes an integer or an integral float."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"{_safe_repr(value)} must be a number; Booleans and text are not accepted"
    try:
        normalized = float(value)
    except OverflowError:
        return f"{_safe_repr(value)} cannot be normalized to a finite built-in float"
    if not isfinite(normalized):
        return f"{_safe_repr(value)} must be finite"
    if whole and not normalized.is_integer():
        return f"{_safe_repr(value)} must be a whole number"
    return None


def _choice_fields(content: object) -> tuple[tuple[str, object, bool], ...]:
    """``(field, value, whole number?)`` for each field of a whole-domain
    choice, in declared order. Explicit per contract: no reflection."""

    match content:
        case AcquisitionChoice():
            return (
                ("purchase_price", content.purchase_price, False),
                ("acquisition_cost_pct", content.acquisition_cost_pct, False),
            )
        case FinancingChoice():
            return (
                ("ltv", content.ltv, False),
                ("interest_rate", content.interest_rate, False),
                ("amortization", content.amortization, True),
                ("io_period", content.io_period, True),
                ("financing_fee_pct", content.financing_fee_pct, False),
            )
        case DispositionChoice():
            return (("hold_period", content.hold_period, True),)
        case _:
            raise TypeError(f"Not a whole-domain choice: {type(content).__qualname__}.")


def _whole_domain_issues(overlay: StrategyOverlay, unit_id: str) -> list[StrategyIssue]:
    """Whole-domain completeness (ST-2), then each value. A missing field makes
    the overlay incomplete; it is never filled from Base."""

    domain = overlay.domain
    fields = _choice_fields(overlay.content)
    stated = ", ".join(name for name, _, _ in fields)
    issues: list[StrategyIssue] = []
    for name, value, whole in fields:
        if value is None:
            issues.append(
                _strategy_issue(
                    StrategyIssueCode.INCOMPLETE_DOMAIN,
                    f"{domain.value}: {name} is missing. A {domain.value} overlay replaces "
                    f"the whole domain and states every field ({stated}); an omitted field "
                    "is never inherited from Base.",
                    domain=domain,
                    unit_id=unit_id,
                    field=name,
                )
            )
            continue
        problem = _value_problem(value, whole=whole)
        if problem is not None:
            issues.append(
                _strategy_issue(
                    StrategyIssueCode.INVALID_NUMBER,
                    f"{domain.value}.{name}: {problem}.",
                    domain=domain,
                    unit_id=unit_id,
                    field=name,
                )
            )
    return issues


def _business_plan_issues(plan: BusinessPlan, unit_id: str) -> list[StrategyIssue]:
    """The D6 validation authority on the replacement plan, unchanged. The plan
    is handed over whole; nothing here reads an item."""

    return [
        _strategy_issue(
            StrategyIssueCode.INVALID_BUSINESS_PLAN,
            f"business_plan.{issue.path}: {issue.message}",
            domain=StrategyDomain.BUSINESS_PLAN,
            unit_id=unit_id,
            field=f"business_plan.{issue.path}",
            source_code=issue.code.value,
        )
        for issue in validate_business_plan(plan).issues
    ]


def _outcome_target_issue(
    target: ScenarioTarget, operating_mode: OperatingMode, unit_id: str
) -> StrategyIssue | None:
    approved = STRATEGY_OUTCOME_TARGETS[operating_mode]
    if target in approved:
        return None
    if target.value in STRATEGY_DOMAIN_FIELDS[StrategyDomain.FINANCING]:
        message = (
            f"operating_outcome: {target.value} is a financing decision. A strategy "
            "chooses it in its financing overlay, never as an operating outcome."
        )
    else:
        message = (
            f"operating_outcome: {target.value} is not a {operating_mode.value} strategy "
            f"operating outcome; {operating_mode.value} strategies may set: "
            f"{', '.join(candidate.value for candidate in approved)}."
        )
    return _strategy_issue(
        StrategyIssueCode.UNSUPPORTED_TARGET,
        message,
        domain=StrategyDomain.OPERATING_OUTCOME,
        unit_id=unit_id,
        target=target,
    )


def _operating_outcome_issues(
    content: OperatingOutcomeSet, operating_mode: OperatingMode, unit_id: str
) -> list[StrategyIssue]:
    """At least one outcome; registry tokens approved for this mode; at most
    one per target; ``SET`` only; finite values. Reported in registry order,
    whatever order the outcomes were stored in."""

    domain = StrategyDomain.OPERATING_OUTCOME
    outcomes = content.outcomes
    if not isinstance(outcomes, tuple):
        return [
            _strategy_issue(
                StrategyIssueCode.INVALID_CONTENT,
                "operating_outcome: outcomes must be a tuple of OperatingOutcome; got "
                f"{type(outcomes).__qualname__}.",
                domain=domain,
                unit_id=unit_id,
            )
        ]
    if not outcomes:
        return [
            _strategy_issue(
                StrategyIssueCode.INCOMPLETE_DOMAIN,
                "operating_outcome: the overlay states no outcome. It sets at least one; "
                "to keep every Base operating assumption, omit the overlay.",
                domain=domain,
                unit_id=unit_id,
            )
        ]

    issues: list[StrategyIssue] = []
    for index, outcome in enumerate(outcomes):
        if not isinstance(outcome, OperatingOutcome):
            issues.append(
                _strategy_issue(
                    StrategyIssueCode.INVALID_CONTENT,
                    f"operating_outcome: outcomes[{index}] must be an OperatingOutcome; got "
                    f"{type(outcome).__qualname__}.",
                    domain=domain,
                    unit_id=unit_id,
                )
            )

    typed = [outcome for outcome in outcomes if isinstance(outcome, OperatingOutcome)]
    unknown = sorted(
        (outcome for outcome in typed if not isinstance(outcome.target, ScenarioTarget)),
        key=lambda outcome: _safe_repr(outcome.target),
    )
    for outcome in unknown:
        issues.append(
            _strategy_issue(
                StrategyIssueCode.UNSUPPORTED_TARGET,
                f"operating_outcome: unknown target {_safe_repr(outcome.target)}; an "
                "outcome names a Scenario Target Registry token.",
                domain=domain,
                unit_id=unit_id,
            )
        )

    by_target: dict[ScenarioTarget, list[OperatingOutcome]] = {}
    for outcome in typed:
        if isinstance(outcome.target, ScenarioTarget):
            by_target.setdefault(outcome.target, []).append(outcome)

    for target in sorted(by_target, key=lambda candidate: _TARGET_RANK[candidate]):
        occurrences = by_target[target]
        if len(occurrences) > 1:
            issues.append(
                _strategy_issue(
                    StrategyIssueCode.DUPLICATE_TARGET,
                    f"operating_outcome: {len(occurrences)} outcomes set {target.value}; an "
                    "overlay sets each target at most once.",
                    domain=domain,
                    unit_id=unit_id,
                    target=target,
                )
            )
            continue
        (outcome,) = occurrences
        target_issue = _outcome_target_issue(target, operating_mode, unit_id)
        if target_issue is not None:
            issues.append(target_issue)
        operation = outcome.operation
        if not isinstance(operation, ScenarioOperation):
            issues.append(
                _strategy_issue(
                    StrategyIssueCode.INVALID_OPERATION,
                    f"operating_outcome.{target.value}: unknown operation "
                    f"{_safe_repr(operation)}; a strategy outcome uses set.",
                    domain=domain,
                    unit_id=unit_id,
                    target=target,
                )
            )
        elif operation is not ScenarioOperation.SET:
            issues.append(
                _strategy_issue(
                    StrategyIssueCode.INVALID_OPERATION,
                    f"operating_outcome.{target.value}: operation {operation.value!r} is not "
                    "allowed. A strategy states the value it underwrites (set); relative "
                    "operations are Scenario operations.",
                    domain=domain,
                    unit_id=unit_id,
                    target=target,
                )
            )
        problem = (
            "the value is missing"
            if outcome.value is None
            else _value_problem(outcome.value, whole=False)
        )
        if problem is not None:
            issues.append(
                _strategy_issue(
                    StrategyIssueCode.INVALID_NUMBER,
                    f"operating_outcome.{target.value}: {problem}.",
                    domain=domain,
                    unit_id=unit_id,
                    target=target,
                )
            )
    return issues


def _content_issues(
    overlay: StrategyOverlay, operating_mode: OperatingMode, unit_id: str
) -> list[StrategyIssue]:
    """The rules of one overlay that stage 1 has already proven to address
    ``unit_id``, once, in a supported domain."""

    domain = overlay.domain
    content = overlay.content
    expected = _CONTENT_TYPES[domain]
    if not isinstance(content, expected):
        return [
            _strategy_issue(
                StrategyIssueCode.INVALID_CONTENT,
                f"{domain.value}: content must be a {expected.__name__}; got "
                f"{type(content).__qualname__}.",
                domain=domain,
                unit_id=unit_id,
            )
        ]
    match content:
        case BusinessPlan():
            return _business_plan_issues(content, unit_id)
        case OperatingOutcomeSet():
            return _operating_outcome_issues(content, operating_mode, unit_id)
        case AcquisitionChoice() | FinancingChoice() | DispositionChoice():
            return _whole_domain_issues(overlay, unit_id)
        case _:
            raise TypeError(f"No rules for strategy content {type(content).__qualname__}.")


def _address_order(address: tuple[StrategyDomain, str]) -> tuple[int, str]:
    domain, unit = address
    return _DOMAIN_RANK[domain], unit


def validate_strategy(
    strategy: StrategyDefinition, *, operating_mode: OperatingMode, unit_id: str
) -> tuple[StrategyIssue, ...]:
    """Stage 1: every issue in ``strategy`` as a contract for the one Unit
    ``unit_id``, analysed in ``operating_mode``. The order is deterministic and
    never depends on how the overlays were stored:

    1. identity and naming;
    2. a malformed overlay collection, or malformed members of it;
    3. overlays in an unsupported domain (including every later-gate domain);
    4. overlays whose ``unit_id`` is not a nonblank string;
    5. per ``(domain, unit_id)`` address, domains in declaration order, then
       units in sorted order:
       - a duplicate address, reported once and never composed;
       - else an address on any unit other than ``unit_id``
         (``UNIT_NOT_IN_VARIANT``), never ignored or applied to this unit;
       - else the domain's own rules, operating outcomes in registry order.

    Returns ``()`` for a valid strategy. Whether the strategy yields valid
    underwriting is not asked here: that belongs to the variant."""

    if not isinstance(strategy, StrategyDefinition):
        raise TypeError(
            f"strategy must be a StrategyDefinition; got {type(strategy).__qualname__}."
        )
    if not isinstance(operating_mode, OperatingMode):
        raise TypeError(
            "operating_mode must be an OperatingMode; got "
            f"{type(operating_mode).__qualname__}."
        )
    _require_unit_identity(unit_id)

    issues = _header_issues(strategy)

    overlays = strategy.overlays
    if not isinstance(overlays, tuple):
        issues.append(
            _strategy_issue(
                StrategyIssueCode.INVALID_OVERLAYS,
                "overlays must be a tuple of StrategyOverlay; got "
                f"{type(overlays).__qualname__}.",
            )
        )
        return tuple(issues)

    for index, overlay in enumerate(overlays):
        if not isinstance(overlay, StrategyOverlay):
            issues.append(
                _strategy_issue(
                    StrategyIssueCode.INVALID_OVERLAYS,
                    f"overlays[{index}] must be a StrategyOverlay; got "
                    f"{type(overlay).__qualname__}.",
                )
            )

    typed = [overlay for overlay in overlays if isinstance(overlay, StrategyOverlay)]
    unsupported = sorted(
        (overlay for overlay in typed if not isinstance(overlay.domain, StrategyDomain)),
        key=lambda overlay: (_safe_repr(overlay.domain), _safe_repr(overlay.unit_id)),
    )
    for overlay in unsupported:
        issues.append(
            _strategy_issue(
                StrategyIssueCode.UNSUPPORTED_DOMAIN,
                f"Unsupported strategy domain {_safe_repr(overlay.domain)}. A P7.4 "
                "strategy overlays only: "
                f"{', '.join(domain.value for domain in StrategyDomain)}.",
                unit_id=overlay.unit_id if _is_nonblank_text(overlay.unit_id) else None,
            )
        )

    supported = [overlay for overlay in typed if isinstance(overlay.domain, StrategyDomain)]
    unaddressed = sorted(
        (overlay for overlay in supported if not _is_nonblank_text(overlay.unit_id)),
        key=lambda overlay: (_DOMAIN_RANK[overlay.domain], _safe_repr(overlay.unit_id)),
    )
    for overlay in unaddressed:
        issues.append(
            _strategy_issue(
                StrategyIssueCode.INVALID_UNIT_ID,
                f"{overlay.domain.value}: unit_id {_safe_repr(overlay.unit_id)} must be a "
                "nonblank string naming the Unit (Deal) the overlay applies to. Every "
                "P7.4 domain is unit-scoped; there is no investment-scoped overlay.",
                domain=overlay.domain,
            )
        )

    by_address: dict[tuple[StrategyDomain, str], list[StrategyOverlay]] = {}
    for overlay in supported:
        if _is_nonblank_text(overlay.unit_id):
            by_address.setdefault((overlay.domain, overlay.unit_id), []).append(overlay)

    for address in sorted(by_address, key=_address_order):
        domain, overlay_unit = address
        occurrences = by_address[address]
        if len(occurrences) > 1:
            issues.append(
                _strategy_issue(
                    StrategyIssueCode.DUPLICATE_DOMAIN,
                    f"{domain.value}: {len(occurrences)} overlays address unit "
                    f"{_safe_repr(overlay_unit)}; a strategy holds at most one overlay per "
                    "(domain, unit_id), and overlays are never composed.",
                    domain=domain,
                    unit_id=overlay_unit,
                )
            )
        elif overlay_unit != unit_id:
            issues.append(
                _strategy_issue(
                    StrategyIssueCode.UNIT_NOT_IN_VARIANT,
                    f"{domain.value}: the overlay addresses unit {_safe_repr(overlay_unit)}, "
                    f"which is not in this analysis; it resolves unit {_safe_repr(unit_id)} "
                    "only. The overlay is refused, never ignored and never applied to "
                    "another unit.",
                    domain=domain,
                    unit_id=overlay_unit,
                )
            )
        else:
            issues.extend(_content_issues(occurrences[0], operating_mode, unit_id))

    return tuple(issues)


def _require_resolvable(
    strategy: StrategyDefinition, operating_mode: OperatingMode, unit_id: str
) -> tuple[StrategyOverlay, ...]:
    """Raise on any stage-1 issue; otherwise return **every** overlay, in
    domain declaration order. Stage 1 has proven each addresses ``unit_id`` in
    a distinct domain, so nothing is filtered here and nothing is dropped."""

    issues = validate_strategy(strategy, operating_mode=operating_mode, unit_id=unit_id)
    if issues:
        raise StrategyValidationError(issues)
    return tuple(sorted(strategy.overlays, key=lambda overlay: _DOMAIN_RANK[overlay.domain]))


# =============================================================================
# Resolution -- each domain writes only the fields it owns
# =============================================================================

_TermsT = TypeVar("_TermsT", AcquisitionInputs, AcquisitionTerms)


def _with_acquisition(terms: _TermsT, choice: AcquisitionChoice) -> _TermsT:
    return replace(
        terms,
        purchase_price=float(choice.purchase_price),
        acquisition_cost_pct=float(choice.acquisition_cost_pct),
    )


def _with_financing(terms: _TermsT, choice: FinancingChoice) -> _TermsT:
    return replace(
        terms,
        ltv=float(choice.ltv),
        interest_rate=float(choice.interest_rate),
        amortization=int(choice.amortization),
        io_period=int(choice.io_period),
        financing_fee_pct=float(choice.financing_fee_pct),
    )


def _with_disposition(terms: _TermsT, choice: DispositionChoice) -> _TermsT:
    return replace(terms, hold_period=int(choice.hold_period))


def _outcome_overrides(
    outcomes: OperatingOutcomeSet, unit_id: str
) -> tuple[ScenarioOverride, ...]:
    """Each outcome as the P7.1 ``SET`` override on this unit, in registry
    order. Its value is the analyst's own figure and nothing else."""

    return tuple(
        ScenarioOverride(
            unit_id=unit_id,
            target=outcome.target,
            operation=ScenarioOperation.SET,
            value=float(outcome.value),
        )
        for outcome in sorted(outcomes.outcomes, key=lambda outcome: _TARGET_RANK[outcome.target])
    )


def _quick_with_outcomes(
    inputs: AcquisitionInputs, outcomes: OperatingOutcomeSet, unit_id: str
) -> AcquisitionInputs:
    for override in _outcome_overrides(outcomes, unit_id):
        inputs = _resolve_quick_target(inputs, override)
    return inputs


def _detailed_with_outcomes(
    resolved: ResolvedDetailedInputs, outcomes: OperatingOutcomeSet, unit_id: str
) -> ResolvedDetailedInputs:
    for override in _outcome_overrides(outcomes, unit_id):
        resolved = _resolve_detailed_target(resolved, override)
    return resolved


def _lease_level_with_outcomes(
    resolved: ResolvedLeaseLevelInputs, outcomes: OperatingOutcomeSet, unit_id: str
) -> ResolvedLeaseLevelInputs:
    for override in _outcome_overrides(outcomes, unit_id):
        resolved = _resolve_lease_level_target(resolved, override)
    return resolved


def _no_domain_resolver(domain: object) -> ValueError:
    return ValueError(f"No resolver exists for strategy domain {_safe_repr(domain)}.")


def _apply_quick_overlay(
    resolved: ResolvedQuickInputs, overlay: StrategyOverlay, unit_id: str
) -> ResolvedQuickInputs:
    content = overlay.content
    match overlay.domain:
        case StrategyDomain.ACQUISITION:
            assert isinstance(content, AcquisitionChoice)
            return replace(resolved, inputs=_with_acquisition(resolved.inputs, content))
        case StrategyDomain.FINANCING:
            assert isinstance(content, FinancingChoice)
            return replace(resolved, inputs=_with_financing(resolved.inputs, content))
        case StrategyDomain.BUSINESS_PLAN:
            assert isinstance(content, BusinessPlan)
            return replace(resolved, business_plan=content)
        case StrategyDomain.OPERATING_OUTCOME:
            assert isinstance(content, OperatingOutcomeSet)
            return replace(resolved, inputs=_quick_with_outcomes(resolved.inputs, content, unit_id))
        case StrategyDomain.DISPOSITION:
            assert isinstance(content, DispositionChoice)
            return replace(resolved, inputs=_with_disposition(resolved.inputs, content))
        case _:
            raise _no_domain_resolver(overlay.domain)


def _apply_detailed_overlay(
    resolved: ResolvedDetailedInputs, overlay: StrategyOverlay, unit_id: str
) -> ResolvedDetailedInputs:
    content = overlay.content
    match overlay.domain:
        case StrategyDomain.ACQUISITION:
            assert isinstance(content, AcquisitionChoice)
            return replace(resolved, terms=_with_acquisition(resolved.terms, content))
        case StrategyDomain.FINANCING:
            assert isinstance(content, FinancingChoice)
            return replace(resolved, terms=_with_financing(resolved.terms, content))
        case StrategyDomain.BUSINESS_PLAN:
            assert isinstance(content, BusinessPlan)
            return replace(resolved, business_plan=content)
        case StrategyDomain.OPERATING_OUTCOME:
            assert isinstance(content, OperatingOutcomeSet)
            return _detailed_with_outcomes(resolved, content, unit_id)
        case StrategyDomain.DISPOSITION:
            assert isinstance(content, DispositionChoice)
            return replace(resolved, terms=_with_disposition(resolved.terms, content))
        case _:
            raise _no_domain_resolver(overlay.domain)


def _apply_lease_level_overlay(
    resolved: ResolvedLeaseLevelInputs, overlay: StrategyOverlay, unit_id: str
) -> ResolvedLeaseLevelInputs:
    content = overlay.content
    match overlay.domain:
        case StrategyDomain.ACQUISITION:
            assert isinstance(content, AcquisitionChoice)
            return replace(resolved, terms=_with_acquisition(resolved.terms, content))
        case StrategyDomain.FINANCING:
            assert isinstance(content, FinancingChoice)
            return replace(resolved, terms=_with_financing(resolved.terms, content))
        case StrategyDomain.BUSINESS_PLAN:
            assert isinstance(content, BusinessPlan)
            return replace(resolved, business_plan=content)
        case StrategyDomain.OPERATING_OUTCOME:
            assert isinstance(content, OperatingOutcomeSet)
            return _lease_level_with_outcomes(resolved, content, unit_id)
        case StrategyDomain.DISPOSITION:
            assert isinstance(content, DispositionChoice)
            return replace(resolved, terms=_with_disposition(resolved.terms, content))
        case _:
            raise _no_domain_resolver(overlay.domain)


def _sets_renewal_probability(overlays: tuple[StrategyOverlay, ...]) -> bool:
    return any(
        isinstance(overlay.content, OperatingOutcomeSet)
        and any(
            outcome.target is ScenarioTarget.RENEWAL_PROBABILITY
            for outcome in overlay.content.outcomes
        )
        for overlay in overlays
    )


def _lease_level_applicability_issues(
    overlays: tuple[StrategyOverlay, ...], suites: tuple[Suite, ...], unit_id: str
) -> tuple[StrategyIssue, ...]:
    """``renewal_probability`` is a property-default target. A suite with a
    full ``market_leasing_override`` takes its renewal probability from that
    record alone (D0 Section 24.2), so a strategy outcome on the default would
    silently skip it. As P7.1 does for the same target, the outcome is refused
    rather than partly applied. The rent roll is Base and can change after the
    strategy is saved, so this is a variant question, asked at resolution."""

    if not _sets_renewal_probability(overlays):
        return ()
    shadowing = tuple(
        suite.suite_id for suite in suites if suite.market_leasing_override is not None
    )
    if not shadowing:
        return ()
    return (
        _strategy_issue(
            StrategyIssueCode.TARGET_SHADOWED_BY_SUITE_OVERRIDE,
            "operating_outcome.renewal_probability: suite(s) "
            f"{', '.join(shadowing)} carry a full market_leasing_override that shadows the "
            "property-default renewal probability, so this outcome would not reach them. "
            "It is refused rather than partly applied.",
            domain=StrategyDomain.OPERATING_OUTCOME,
            unit_id=unit_id,
            target=ScenarioTarget.RENEWAL_PROBABILITY,
        ),
    )


# =============================================================================
# Public Strategy resolvers -- one Unit per call, no Scenario, no validation
# =============================================================================


def resolve_quick_strategy(
    inputs: AcquisitionInputs,
    *,
    unit_id: str,
    strategy: StrategyDefinition,
    business_plan: BusinessPlan,
) -> ResolvedQuickInputs:
    """Apply ``strategy``'s overlays to the Quick inputs and Business Plan of
    the Unit ``unit_id``, in domain declaration order.

    Raises ``StrategyValidationError`` with stage-1 issues. The result is the
    Strategy-resolved world, before any Scenario: an intermediate that is
    validated only as a variant's final inputs (``resolve_quick_variant``).
    ``inputs`` and ``business_plan`` are never mutated, and a contract no
    overlay changes comes back as the caller's own object."""

    _require_instance(inputs, AcquisitionInputs, "inputs")
    _require_instance(business_plan, BusinessPlan, "business_plan")
    overlays = _require_resolvable(strategy, OperatingMode.QUICK, unit_id)

    resolved = ResolvedQuickInputs(inputs=inputs, business_plan=business_plan)
    for overlay in overlays:
        resolved = _apply_quick_overlay(resolved, overlay, unit_id)
    return resolved


def resolve_detailed_strategy(
    terms: AcquisitionTerms,
    detailed_operating_inputs: DetailedOperatingInputs,
    *,
    unit_id: str,
    strategy: StrategyDefinition,
    business_plan: BusinessPlan,
) -> ResolvedDetailedInputs:
    """The Detailed counterpart of ``resolve_quick_strategy``."""

    _require_instance(terms, AcquisitionTerms, "terms")
    _require_instance(
        detailed_operating_inputs, DetailedOperatingInputs, "detailed_operating_inputs"
    )
    _require_instance(business_plan, BusinessPlan, "business_plan")
    overlays = _require_resolvable(strategy, OperatingMode.DETAILED, unit_id)

    resolved = ResolvedDetailedInputs(
        terms=terms,
        detailed_operating_inputs=detailed_operating_inputs,
        business_plan=business_plan,
    )
    for overlay in overlays:
        resolved = _apply_detailed_overlay(resolved, overlay, unit_id)
    return resolved


def resolve_lease_level_strategy(
    terms: AcquisitionTerms,
    property_inputs: LeaseLevelPropertyInputs,
    suites: Iterable[Suite],
    leases: Iterable[Lease],
    *,
    market_leasing: MarketLeasingAssumptions,
    operating_inputs: LeaseLevelOperatingInputs,
    unit_id: str,
    strategy: StrategyDefinition,
    business_plan: BusinessPlan,
) -> ResolvedLeaseLevelInputs:
    """The Lease-Level counterpart of ``resolve_quick_strategy``.

    A ``market_rent_psf`` outcome sets the analyst's figure on every
    market-rent level the configuration states -- the property default and
    every suite's scalar or full-override rent -- through the P7.1 resolver,
    so every suite's resolved market rent is the strategy's figure. The
    suites come back as a new configuration and the caller's are untouched.
    A ``renewal_probability`` outcome that a suite override shadows is
    refused (``TARGET_SHADOWED_BY_SUITE_OVERRIDE``)."""

    _require_instance(terms, AcquisitionTerms, "terms")
    _require_instance(property_inputs, LeaseLevelPropertyInputs, "property_inputs")
    _require_instance(market_leasing, MarketLeasingAssumptions, "market_leasing")
    _require_instance(operating_inputs, LeaseLevelOperatingInputs, "operating_inputs")
    _require_instance(business_plan, BusinessPlan, "business_plan")
    suite_tuple = tuple(suites)
    lease_tuple = tuple(leases)

    overlays = _require_resolvable(strategy, OperatingMode.LEASE_LEVEL, unit_id)
    shadowed = _lease_level_applicability_issues(overlays, suite_tuple, unit_id)
    if shadowed:
        raise StrategyValidationError(shadowed)

    resolved = ResolvedLeaseLevelInputs(
        terms=terms,
        property_inputs=property_inputs,
        suites=suite_tuple,
        leases=lease_tuple,
        market_leasing=market_leasing,
        operating_inputs=operating_inputs,
        business_plan=business_plan,
    )
    for overlay in overlays:
        resolved = _apply_lease_level_overlay(resolved, overlay, unit_id)
    return resolved


# =============================================================================
# Final validation -- the existing validators, on the variant's final inputs
# =============================================================================


def _applied_fields(
    overlays: tuple[StrategyOverlay, ...],
) -> Mapping[str, tuple[StrategyDomain, ScenarioTarget | None]]:
    """For each field the strategy writes: its domain, and its outcome target
    where it is one. Used only to attribute a validator's finding."""

    applied: dict[str, tuple[StrategyDomain, ScenarioTarget | None]] = {}
    for overlay in overlays:
        if isinstance(overlay.content, OperatingOutcomeSet):
            for outcome in overlay.content.outcomes:
                applied[outcome.target.value] = (overlay.domain, outcome.target)
        else:
            for field in STRATEGY_DOMAIN_FIELDS[overlay.domain]:
                applied[field] = (overlay.domain, None)
    return applied


def _resolved_input_issue(
    *,
    message: str,
    field: str | None,
    source_code: str,
    applied: Mapping[str, tuple[StrategyDomain, ScenarioTarget | None]],
    unit_id: str,
) -> StrategyIssue:
    """Wrap one existing finding, unchanged. A finding on a field the strategy
    wrote is attributed to that domain (and outcome target); any other finding
    -- a defect already in the Base inputs -- names no domain."""

    leaf = None if field is None else field.rpartition(".")[2]
    domain, target = applied.get(leaf, (None, None)) if leaf is not None else (None, None)
    return StrategyIssue(
        stage=StrategyIssueStage.RESOLVED_INPUTS,
        code=StrategyIssueCode.RESOLVED_INPUT_INVALID,
        message=message,
        domain=domain,
        unit_id=unit_id,
        field=field,
        target=target,
        source_code=source_code,
    )


def _input_error_issues(
    error: InputValidationError,
    applied: Mapping[str, tuple[StrategyDomain, ScenarioTarget | None]],
    unit_id: str,
) -> list[StrategyIssue]:
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
    applied: Mapping[str, tuple[StrategyDomain, ScenarioTarget | None]],
    unit_id: str,
) -> list[StrategyIssue]:
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
    inputs: AcquisitionInputs,
    applied: Mapping[str, tuple[StrategyDomain, ScenarioTarget | None]],
    unit_id: str,
) -> list[StrategyIssue]:
    try:
        validate_acquisition_inputs(asdict(inputs))
    except InputValidationError as error:
        return _input_error_issues(error, applied, unit_id)
    return []


def _terms_issues(
    terms: AcquisitionTerms,
    applied: Mapping[str, tuple[StrategyDomain, ScenarioTarget | None]],
    unit_id: str,
) -> list[StrategyIssue]:
    try:
        validate_acquisition_terms(asdict(terms))
    except InputValidationError as error:
        return _input_error_issues(error, applied, unit_id)
    return []


def _detailed_operating_issues(
    operating: DetailedOperatingInputs,
    applied: Mapping[str, tuple[StrategyDomain, ScenarioTarget | None]],
    unit_id: str,
) -> list[StrategyIssue]:
    try:
        validate_detailed_operating_inputs(asdict(operating))
    except InputValidationError as error:
        return _input_error_issues(error, applied, unit_id)
    return []


def _final_plan_issues(plan: BusinessPlan, unit_id: str) -> list[StrategyIssue]:
    return [
        StrategyIssue(
            stage=StrategyIssueStage.RESOLVED_INPUTS,
            code=StrategyIssueCode.RESOLVED_INPUT_INVALID,
            message=issue.message,
            domain=StrategyDomain.BUSINESS_PLAN,
            unit_id=unit_id,
            field=f"business_plan.{issue.path}",
            source_code=issue.code.value,
        )
        for issue in validate_business_plan(plan).issues
    ]


def _require_no_issues(issues: list[StrategyIssue]) -> None:
    if issues:
        raise StrategyValidationError(issues)


# =============================================================================
# Variants -- Base -> Strategy -> Scenario -> validation, one Unit per call
# =============================================================================


def resolve_quick_variant(
    inputs: AcquisitionInputs,
    *,
    unit_id: str,
    strategy: StrategyDefinition,
    scenario: ScenarioDefinition | None,
    business_plan: BusinessPlan,
) -> ResolvedQuickInputs:
    """Resolve the Quick variant ``(strategy, scenario)`` of the Unit
    ``unit_id``: exactly what its analysis runs.

    ``scenario`` is ``None`` for the implicit Base Scenario. Otherwise the
    P7.1 resolver runs on the Strategy-resolved contracts, so every relative
    operation acts on the strategy's value. Then every final contract that is
    not the Deal's own object is validated by its existing validator.

    Raises ``StrategyValidationError`` (the strategy contract, or a final
    input the strategy made invalid) or ``ScenarioValidationError`` (the
    scenario contract, or a value the scenario made invalid). Nothing is ever
    clipped, and nothing the caller passed is mutated."""

    chosen = resolve_quick_strategy(
        inputs, unit_id=unit_id, strategy=strategy, business_plan=business_plan
    )
    resolved = chosen
    if scenario is not None:
        resolved = resolve_quick_scenario(
            chosen.inputs, unit_id=unit_id, scenario=scenario, business_plan=chosen.business_plan
        )

    applied = _applied_fields(strategy.overlays)
    issues: list[StrategyIssue] = []
    if resolved.inputs is not inputs:
        issues.extend(_quick_input_issues(resolved.inputs, applied, unit_id))
    if resolved.business_plan is not business_plan:
        issues.extend(_final_plan_issues(resolved.business_plan, unit_id))
    _require_no_issues(issues)
    return resolved


def resolve_detailed_variant(
    terms: AcquisitionTerms,
    detailed_operating_inputs: DetailedOperatingInputs,
    *,
    unit_id: str,
    strategy: StrategyDefinition,
    scenario: ScenarioDefinition | None,
    business_plan: BusinessPlan,
) -> ResolvedDetailedInputs:
    """The Detailed counterpart of ``resolve_quick_variant``."""

    chosen = resolve_detailed_strategy(
        terms,
        detailed_operating_inputs,
        unit_id=unit_id,
        strategy=strategy,
        business_plan=business_plan,
    )
    resolved = chosen
    if scenario is not None:
        resolved = resolve_detailed_scenario(
            chosen.terms,
            chosen.detailed_operating_inputs,
            unit_id=unit_id,
            scenario=scenario,
            business_plan=chosen.business_plan,
        )

    applied = _applied_fields(strategy.overlays)
    issues: list[StrategyIssue] = []
    if resolved.terms is not terms:
        issues.extend(_terms_issues(resolved.terms, applied, unit_id))
    if resolved.detailed_operating_inputs is not detailed_operating_inputs:
        issues.extend(
            _detailed_operating_issues(resolved.detailed_operating_inputs, applied, unit_id)
        )
    if resolved.business_plan is not business_plan:
        issues.extend(_final_plan_issues(resolved.business_plan, unit_id))
    _require_no_issues(issues)
    return resolved


def resolve_lease_level_variant(
    terms: AcquisitionTerms,
    property_inputs: LeaseLevelPropertyInputs,
    suites: Iterable[Suite],
    leases: Iterable[Lease],
    *,
    market_leasing: MarketLeasingAssumptions,
    operating_inputs: LeaseLevelOperatingInputs,
    unit_id: str,
    strategy: StrategyDefinition,
    scenario: ScenarioDefinition | None,
    business_plan: BusinessPlan,
) -> ResolvedLeaseLevelInputs:
    """The Lease-Level counterpart of ``resolve_quick_variant``.

    The rent roll and its market records are validated whenever the terms,
    the market record or the suites differ from the Deal's own, because the
    leasing validator reads the hold period, and a DISPOSITION overlay can
    change it. Downstream conditions only the full analysis can meet stay with
    the analysis (the P7.1 rule), and raise from it exactly as they would for
    the same inputs entered by hand."""

    suite_tuple = tuple(suites)
    lease_tuple = tuple(leases)
    chosen = resolve_lease_level_strategy(
        terms,
        property_inputs,
        suite_tuple,
        lease_tuple,
        market_leasing=market_leasing,
        operating_inputs=operating_inputs,
        unit_id=unit_id,
        strategy=strategy,
        business_plan=business_plan,
    )
    resolved = chosen
    if scenario is not None:
        resolved = resolve_lease_level_scenario(
            chosen.terms,
            chosen.property_inputs,
            chosen.suites,
            chosen.leases,
            market_leasing=chosen.market_leasing,
            operating_inputs=chosen.operating_inputs,
            unit_id=unit_id,
            scenario=scenario,
            business_plan=chosen.business_plan,
        )

    applied = _applied_fields(strategy.overlays)
    issues: list[StrategyIssue] = []
    if resolved.terms is not terms:
        issues.extend(_terms_issues(resolved.terms, applied, unit_id))
    if (
        resolved.terms is not terms
        or resolved.market_leasing is not market_leasing
        or resolved.suites is not suite_tuple
    ):
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
    if resolved.operating_inputs is not operating_inputs:
        issues.extend(
            _lease_error_issues(
                validate_lease_level_operating_inputs(resolved.operating_inputs).errors,
                applied,
                unit_id,
            )
        )
    if resolved.business_plan is not business_plan:
        issues.extend(_final_plan_issues(resolved.business_plan, unit_id))
    _require_no_issues(issues)
    return resolved


# =============================================================================
# Analysis -- the existing entry points on the resolved inputs
# =============================================================================


def analyze_quick_acquisition_with_strategy(
    inputs: AcquisitionInputs,
    *,
    unit_id: str,
    strategy: StrategyDefinition,
    scenario: ScenarioDefinition | None,
    business_plan: BusinessPlan,
) -> AcquisitionResults:
    """Resolve the variant for the Unit ``unit_id``, then run the existing
    Quick Business Plan entry point on the resolved contracts. There is no
    strategy-specific financial code path: the result is identical to entering
    the resolved assumptions by hand."""

    resolved = resolve_quick_variant(
        inputs, unit_id=unit_id, strategy=strategy, scenario=scenario, business_plan=business_plan
    )
    return analyze_quick_acquisition_with_business_plan(
        resolved.inputs, business_plan=resolved.business_plan
    )


def analyze_detailed_acquisition_with_strategy(
    terms: AcquisitionTerms,
    detailed_operating_inputs: DetailedOperatingInputs,
    *,
    unit_id: str,
    strategy: StrategyDefinition,
    scenario: ScenarioDefinition | None,
    business_plan: BusinessPlan,
) -> DetailedAcquisitionResults:
    """Resolve the variant, then run the existing Detailed Business Plan entry
    point on the resolved contracts."""

    resolved = resolve_detailed_variant(
        terms,
        detailed_operating_inputs,
        unit_id=unit_id,
        strategy=strategy,
        scenario=scenario,
        business_plan=business_plan,
    )
    return analyze_detailed_acquisition_with_business_plan(
        resolved.terms,
        resolved.detailed_operating_inputs,
        business_plan=resolved.business_plan,
    )


def analyze_lease_level_acquisition_with_strategy(
    terms: AcquisitionTerms,
    property_inputs: LeaseLevelPropertyInputs,
    suites: Iterable[Suite],
    leases: Iterable[Lease],
    *,
    market_leasing: MarketLeasingAssumptions,
    operating_inputs: LeaseLevelOperatingInputs,
    unit_id: str,
    strategy: StrategyDefinition,
    scenario: ScenarioDefinition | None,
    business_plan: BusinessPlan,
) -> LeaseLevelAcquisitionResults:
    """Resolve the variant, then run the existing Lease-Level Business Plan
    entry point on the resolved contracts."""

    resolved = resolve_lease_level_variant(
        terms,
        property_inputs,
        suites,
        leases,
        market_leasing=market_leasing,
        operating_inputs=operating_inputs,
        unit_id=unit_id,
        strategy=strategy,
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
