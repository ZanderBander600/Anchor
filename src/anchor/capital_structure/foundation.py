"""Phase 7 Gate P7.7 -- the neutral Capital Structure facade.

Restates ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections
3 (P-3, P-4, P-9, P-11, P-14, P-15), 12 and 14, and the Section 21 record (Q12,
Q13); that document governs on any discrepancy. P7.7 carries the Q16
engine-scope approval for this layer: new downstream contracts, structural
validation, deterministic claim settlement and Funding Requirement reporting,
the read-only legacy adapter and this facade. No Property, NOI, exit,
acquisition-debt, owner cash-flow, consolidation or IRR formula moves.

**Downstream and one-way (P-4).** Capital Structure reads completed
``AcquisitionResults`` and ``ConsolidatedResults`` and writes nothing back. It
never alters NOI, Property Cash Flow, Project Capital, Owner Expenses, exit NOI,
exit value or disposition costs.

**The pre-capital-structure handoff**::

    Unit     unlevered_cash_flows        pre-acquisition-debt authority
                  |   the acquisition loan, adapted (read, never applied)
             levered_cash_flows          post-acquisition-debt authority
                  |                      = Common Equity Cash Flow today
    Investment  ConsolidatedResults.levered_cash_flows
                                         after every Unit's positions and
                                         the Investment-level channels

The acquisition loan already bridges the first two, inside the engine. The
facade therefore passes the post-debt series through untouched; subtracting the
loan's debt service, balance or fee from it again would count the loan twice. An
Investment-scoped position reads only the consolidated levered figures, never the
consolidated unlevered series while Unit loans exist.

**Executable scope.** Each Unit's existing acquisition loan and the implicit
residual common equity -- nothing else. An authored position of any class fails
closed with ``UnsupportedCapitalPositionError``; it is never ignored and never
partially executed. No new position cash flow, return, accrual, refinancing or
partnership economics exists here.

**Funding Requirements.** ``settle_claim`` settles one stated claim against
stated eligible cash under the claim's explicit resolution. A resolved shortfall
is met by exactly the shortfall in common equity; an unresolved one leaves the
claim part-unpaid and makes the Common Equity Cash Flow unavailable, with a
reason naming the requirement, rather than fabricated.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from math import isfinite

from ..consolidation.contracts import ConsolidatedResults
from ..contracts import AcquisitionTerms
from ..engine.contracts import AcquisitionResults, ensure_finite
from .contracts import (
    MONTHS_PER_HOLD_YEAR,
    CapitalStructure,
    CapitalStructureError,
    CapitalStructureIssue,
    CapitalStructureIssueCode,
    CapitalStructureStatus,
    CapitalStructureUnit,
    CapitalStructureValidationError,
    ClaimPeriod,
    ClaimSettlement,
    CommonEquityOutcome,
    CommonEquityUnavailableReason,
    ContractualClaim,
    FundingRequirement,
    FundingRequirementStatus,
    HoldYearPeriod,
    InvestmentCapitalStructureResult,
    InvestmentScopeCashAuthority,
    LegacyAcquisitionLoan,
    ModelMonthPeriod,
    PositionScope,
    ScopeKind,
    ShortfallResolution,
    UnitCapitalStructureResult,
    UnitCashAuthority,
    UnsupportedCapitalPositionError,
)
from .legacy import adapt_legacy_acquisition_loan, legacy_acquisition_loan_claims
from .validation import economic_order, validate_capital_structure

# =============================================================================
# Timing
# =============================================================================


def annual_period_of_model_month(model_month: int) -> int:
    """The annual cash-flow period ``t`` that a model month falls in, under the
    D6 Section 4 convention exactly. Month ``0`` is closing (``t = 0``); month
    ``m >= 1`` is in hold year ``((m - 1) // 12) + 1``.

    This is the one timing convention, restated rather than imported, so that
    this package depends on no Business Plan or leasing module."""

    if isinstance(model_month, bool) or not isinstance(model_month, int):
        raise TypeError(f"model_month must be a whole model month; got {model_month!r}.")
    if model_month < 0:
        raise ValueError(f"model_month must be >= 0 (0 = closing); got {model_month!r}.")
    if model_month == 0:
        return 0
    return (model_month - 1) // MONTHS_PER_HOLD_YEAR + 1


# =============================================================================
# Claim settlement and Funding Requirements
# =============================================================================


def _period_value(period: ClaimPeriod) -> int:
    match period:
        case HoldYearPeriod():
            return period.hold_year
        case ModelMonthPeriod():
            return period.model_month


def _period_label(period: ClaimPeriod) -> str:
    return f"{period.basis.value.replace('_', ' ')} {_period_value(period)}"


def _scope_label(scope: PositionScope) -> str:
    return f"Unit {scope.unit_id}" if scope.kind is ScopeKind.UNIT else "the Investment"


def _require_settleable(claim: object) -> ContractualClaim:
    if not isinstance(claim, ContractualClaim):
        raise CapitalStructureError(f"Not a ContractualClaim: {type(claim).__qualname__}.")
    if not isinstance(claim.position_id, str) or claim.position_id.strip() == "":
        raise CapitalStructureError(f"A claim names its position; got {claim.position_id!r}.")
    if not isinstance(claim.scope, PositionScope) or not isinstance(claim.scope.kind, ScopeKind):
        raise CapitalStructureError(f"Claim of {claim.position_id!r} has no scope.")
    if isinstance(claim.period, HoldYearPeriod):
        valid_period = isinstance(claim.period.hold_year, int) and not isinstance(claim.period.hold_year, bool) and claim.period.hold_year >= 1
    elif isinstance(claim.period, ModelMonthPeriod):
        valid_period = (
            isinstance(claim.period.model_month, int)
            and not isinstance(claim.period.model_month, bool)
            and claim.period.model_month >= 0
        )
    else:
        valid_period = False
    if not valid_period:
        raise CapitalStructureError(f"Claim of {claim.position_id!r} has no valid period: {claim.period!r}.")
    for name in ("claim_due", "cash_available"):
        value = getattr(claim, name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
            raise CapitalStructureError(f"Claim of {claim.position_id!r}: {name} {value!r} is not a finite number.")
        if value < 0.0:
            raise CapitalStructureError(
                f"Claim of {claim.position_id!r}: {name} {value!r} is negative; only a claim and the eligible, "
                "nonnegative cash available to it can be settled."
            )
    if not isinstance(claim.shortfall_resolution, ShortfallResolution):
        raise CapitalStructureError(
            f"Claim of {claim.position_id!r} states no shortfall resolution ({claim.shortfall_resolution!r}); "
            "one is always explicit and none is assumed."
        )
    return claim


def settle_claim(claim: ContractualClaim) -> ClaimSettlement:
    """Settle one contractual claim against the eligible cash available to it,
    under the claim's own explicit resolution. It discovers nothing: the claim
    and the cash arrive stated.

    - The claim is covered: it is paid from cash, and there is no Funding
      Requirement.
    - Shortfall, ``COMMON_EQUITY_CONTRIBUTION``: the requirement is resolved;
      common equity contributes exactly the shortfall, and the claim is paid in
      full.
    - Shortfall, ``UNRESOLVED``: the requirement is unresolved. Only the
      available cash is paid, the remainder stays unpaid, and no equity
      contribution is invented.

    There is no other cure and no default. Raises ``CapitalStructureError`` for
    a claim it cannot settle, including one without an explicit resolution."""

    claim = _require_settleable(claim)
    due, available = claim.claim_due, claim.cash_available
    if due <= available:
        return ClaimSettlement(
            claim=claim,
            claim_paid=due,
            claim_paid_from_cash=due,
            equity_contribution=0.0,
            unpaid_claim_amount=0.0,
            funding_requirement=None,
        )

    shortfall = ensure_finite("funding_requirement", due - available)
    resolution = claim.shortfall_resolution
    head = (
        f"{claim.position_id} ({_scope_label(claim.scope)}) was owed {due:,.2f} in {_period_label(claim.period)}, "
        f"but only {available:,.2f} of eligible cash was available to it."
    )
    if resolution is ShortfallResolution.COMMON_EQUITY_CONTRIBUTION:
        contribution, unpaid, paid = shortfall, 0.0, due
        status = FundingRequirementStatus.RESOLVED
        tail = (
            f"The {shortfall:,.2f} shortfall is met by an additional common-equity contribution, as this "
            "position's terms state, so the claim is paid in full."
        )
    elif resolution is ShortfallResolution.UNRESOLVED:
        contribution, unpaid, paid = 0.0, shortfall, available
        status = FundingRequirementStatus.UNRESOLVED
        tail = (
            f"The {shortfall:,.2f} shortfall is unresolved: only the available cash is paid, the rest of the "
            "claim stays unpaid, and every figure downstream of it is incomplete."
        )
    else:  # pragma: no cover -- _require_settleable admits only the two members.
        raise CapitalStructureError(f"Unknown shortfall resolution {resolution!r}.")

    requirement = FundingRequirement(
        requirement_id=f"{claim.position_id}/{claim.period.basis.value}/{_period_value(claim.period)}",
        position_id=claim.position_id,
        scope=claim.scope,
        period=claim.period,
        claim_amount=due,
        cash_available=available,
        claim_paid_from_cash=available,
        amount=shortfall,
        equity_contribution=contribution,
        unpaid_claim_amount=unpaid,
        resolution=resolution,
        status=status,
        explanation=f"{head} {tail}",
    )
    return ClaimSettlement(
        claim=claim,
        claim_paid=paid,
        claim_paid_from_cash=available,
        equity_contribution=contribution,
        unpaid_claim_amount=unpaid,
        funding_requirement=requirement,
    )


def common_equity_outcome(
    *, funding_requirements: Iterable[FundingRequirement], residual_cash_flows: tuple[float, ...]
) -> CommonEquityOutcome:
    """The Common Equity Cash Flow downstream of a Capital Structure.

    ``residual_cash_flows`` is the series the structure leaves to common equity,
    and it is returned untouched when every Funding Requirement is resolved.
    When any requirement is unresolved, the structure's downstream economics are
    incomplete. The series is then unavailable (``None``), never zero-filled or
    partial, and the reason names every unresolved requirement in the order
    given. Upstream results are not touched either way."""

    requirements = tuple(funding_requirements)
    unresolved = tuple(
        requirement.requirement_id
        for requirement in requirements
        if requirement.status is FundingRequirementStatus.UNRESOLVED
    )
    if unresolved:
        return CommonEquityOutcome(
            status=CapitalStructureStatus.UNRESOLVED_FUNDING,
            common_equity_cash_flows=None,
            unavailable_reason=CommonEquityUnavailableReason.UNRESOLVED_FUNDING_REQUIREMENT,
            unavailable_message=(
                "The Common Equity Cash Flow is not reported: Funding Requirement(s) "
                f"{', '.join(unresolved)} are unresolved, so every figure downstream of the unpaid claim is "
                "incomplete. Property, Business Plan and project results are unaffected."
            ),
            unresolved_requirement_ids=unresolved,
        )
    return CommonEquityOutcome(
        status=CapitalStructureStatus.COMPLETE,
        common_equity_cash_flows=residual_cash_flows,
        unavailable_reason=None,
        unavailable_message=None,
        unresolved_requirement_ids=(),
    )


# =============================================================================
# The named cash authorities
# =============================================================================


def unit_cash_authority(*, unit_id: str, results: AcquisitionResults) -> UnitCashAuthority:
    """One Unit's pre- and post-acquisition-debt authorities: its completed
    result's own series, passed through."""

    return UnitCashAuthority(
        unit_id=unit_id,
        pre_acquisition_debt_cash_flows=results.unlevered_cash_flows,
        post_acquisition_debt_cash_flows=results.levered_cash_flows,
        owner_cash_flow_after_acquisition_debt_by_year=results.levered_owner_cash_flow_by_year,
        net_sale_proceeds_after_acquisition_debt=results.net_sale_proceeds,
    )


def investment_scope_cash_authority(consolidated: ConsolidatedResults) -> InvestmentScopeCashAuthority:
    """The cash available to an Investment-scoped position: the consolidated
    levered figures, after every Unit's acquisition loan and the
    Investment-level channels (CS-4). Nothing is subtracted here, and the
    consolidated unlevered series is never read."""

    return InvestmentScopeCashAuthority(
        unit_ids=consolidated.unit_ids,
        cash_flows_after_unit_positions=consolidated.levered_cash_flows,
        owner_cash_flow_after_unit_positions_by_year=consolidated.levered_owner_cash_flow_by_year,
        net_sale_proceeds_after_unit_positions=consolidated.net_sale_proceeds,
    )


# =============================================================================
# The executor
# =============================================================================


def _require_executable(
    capital_structure: CapitalStructure | None,
    *,
    member_unit_ids: Collection[str],
    acquisition_loan_unit_ids: Collection[str],
) -> None:
    """P7.7 executes the acquisition loans and the residual only. An invalid
    structure raises ``CapitalStructureValidationError``; a valid structure with
    any authored position raises ``UnsupportedCapitalPositionError``, one issue
    per position in economic order."""

    if capital_structure is None:
        return
    issues = validate_capital_structure(
        capital_structure,
        member_unit_ids=member_unit_ids,
        acquisition_loan_unit_ids=acquisition_loan_unit_ids,
    )
    if issues:
        raise CapitalStructureValidationError(issues)
    authored = economic_order(capital_structure.positions)
    if authored:
        raise UnsupportedCapitalPositionError(
            CapitalStructureIssue(
                code=CapitalStructureIssueCode.UNSUPPORTED_POSITION,
                message=(
                    f"Authored {position.position_class.value} position {position.position_id!r} is not "
                    "executed: this Capital Structure executes only each Unit's existing acquisition loan "
                    "and the residual common equity. Nothing was analysed."
                ),
                position_id=position.position_id,
            )
            for position in authored
        )


def _legacy_requirements(
    loan: LegacyAcquisitionLoan | None, authority: UnitCashAuthority
) -> tuple[FundingRequirement, ...]:
    if loan is None:
        return ()
    settlements = (settle_claim(claim) for claim in legacy_acquisition_loan_claims(loan, cash_authority=authority))
    return tuple(
        settlement.funding_requirement for settlement in settlements if settlement.funding_requirement is not None
    )


def analyze_unit_capital_structure(
    *,
    unit_id: str,
    terms: AcquisitionTerms,
    results: AcquisitionResults,
    capital_structure: CapitalStructure | None = None,
) -> UnitCapitalStructureResult:
    """The Capital Structure foundation of one completed Unit.

    ``terms`` and ``results`` are the Unit's resolved ``AcquisitionTerms`` and
    its completed ``AcquisitionResults``; the acquisition is never re-run.
    ``capital_structure`` holds authored positions; ``None`` and the empty
    structure mean none (P-11). Any authored position is refused.

    Neutrality: ``common_equity_cash_flows`` *is*
    ``results.levered_cash_flows``, bit for bit, passed through."""

    loan = adapt_legacy_acquisition_loan(unit_id=unit_id, terms=terms, results=results)
    _require_executable(
        capital_structure,
        member_unit_ids=(unit_id,),
        acquisition_loan_unit_ids=() if loan is None else (unit_id,),
    )
    authority = unit_cash_authority(unit_id=unit_id, results=results)
    requirements = _legacy_requirements(loan, authority)
    outcome = common_equity_outcome(
        funding_requirements=requirements, residual_cash_flows=authority.post_acquisition_debt_cash_flows
    )
    return UnitCapitalStructureResult(
        unit_id=unit_id,
        status=outcome.status,
        legacy_acquisition_loan=loan,
        funding_requirements=requirements,
        cash_authority=authority,
        common_equity_cash_flows=outcome.common_equity_cash_flows,
        common_equity_unavailable_reason=outcome.unavailable_reason,
        common_equity_unavailable_message=outcome.unavailable_message,
    )


def _require_investment_coherent(
    units: tuple[object, ...], consolidated: object
) -> tuple[CapitalStructureUnit, ...]:
    if not isinstance(consolidated, ConsolidatedResults):
        raise CapitalStructureError(f"Not ConsolidatedResults: {type(consolidated).__qualname__}.")
    for unit in units:
        if not isinstance(unit, CapitalStructureUnit):
            raise CapitalStructureError(f"Not a CapitalStructureUnit: {type(unit).__qualname__}.")
    typed = tuple(unit for unit in units if isinstance(unit, CapitalStructureUnit))
    ordered = tuple(sorted(typed, key=lambda unit: unit.unit_id))
    unit_ids = tuple(unit.unit_id for unit in ordered)
    if len(set(unit_ids)) != len(unit_ids):
        raise CapitalStructureError("A Unit is given more than once.")
    if unit_ids != consolidated.unit_ids:
        raise CapitalStructureError(
            f"The Units given ({', '.join(unit_ids)}) are not the Units consolidated "
            f"({', '.join(consolidated.unit_ids)})."
        )
    for unit in ordered:
        if unit.terms.hold_period != consolidated.hold_period:
            raise CapitalStructureError(
                f"Unit {unit.unit_id!r} holds for {unit.terms.hold_period} years; the Investment holds for "
                f"{consolidated.hold_period}."
            )
    return ordered


def analyze_investment_capital_structure(
    *,
    units: Iterable[CapitalStructureUnit],
    consolidated: ConsolidatedResults,
    capital_structure: CapitalStructure | None = None,
) -> InvestmentCapitalStructureResult:
    """The Capital Structure foundation of a visible Investment.

    ``units`` are the Units' resolved terms and completed results, and
    ``consolidated`` is their completed consolidation. Each Unit's acquisition
    loan is adapted independently, Unit-scoped, in ascending ``unit_id`` order,
    and its Funding Requirements read only that Unit's cash. Any authored
    position is refused.

    Neutrality: ``common_equity_cash_flows`` *is*
    ``consolidated.levered_cash_flows``, bit for bit, passed through; no Unit's
    debt service, balance or fee is subtracted again."""

    ordered = _require_investment_coherent(tuple(units), consolidated)
    loans = {
        unit.unit_id: adapt_legacy_acquisition_loan(unit_id=unit.unit_id, terms=unit.terms, results=unit.results)
        for unit in ordered
    }
    _require_executable(
        capital_structure,
        member_unit_ids=consolidated.unit_ids,
        acquisition_loan_unit_ids=tuple(unit_id for unit_id, loan in loans.items() if loan is not None),
    )
    authorities = tuple(unit_cash_authority(unit_id=unit.unit_id, results=unit.results) for unit in ordered)
    requirements = tuple(
        requirement
        for authority in authorities
        for requirement in _legacy_requirements(loans[authority.unit_id], authority)
    )
    investment_authority = investment_scope_cash_authority(consolidated)
    outcome = common_equity_outcome(
        funding_requirements=requirements,
        residual_cash_flows=investment_authority.cash_flows_after_unit_positions,
    )
    return InvestmentCapitalStructureResult(
        unit_ids=consolidated.unit_ids,
        status=outcome.status,
        legacy_acquisition_loans=tuple(loan for loan in loans.values() if loan is not None),
        funding_requirements=requirements,
        unit_cash_authorities=authorities,
        investment_cash_authority=investment_authority,
        common_equity_cash_flows=outcome.common_equity_cash_flows,
        common_equity_unavailable_reason=outcome.unavailable_reason,
        common_equity_unavailable_message=outcome.unavailable_message,
    )
