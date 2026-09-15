"""Phase 7 Gate P7.7 -- the read-only legacy acquisition-loan adapter.

Restates ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section
12.4 (facade + read-only adapter, ratified in Section 22.5) and CS-7 FR-5; that
document governs on any discrepancy.

**The acquisition loan keeps its owners.** ``AcquisitionTerms`` states it,
``anchor.engine.debt`` computes it and ``AcquisitionResults`` reports it. This
module reads the report and nothing else: it imports no debt function, and never
rebuilds a loan amount, fee, payment, amortization schedule or balance. The
completed result is the one authority.

**Identity.** An adapted loan is ``legacy-acquisition-loan:<unit_id>``: stable
for the Unit, reserved (no authored position may use the prefix), and never
stored. It is Unit-scoped, priority 1, senior debt.

**No loan, no position.** A Unit with ``loan_amount == 0`` has no acquisition
loan; no zero-dollar senior debt is fabricated. Its financing fee, being a
percentage of the loan, is zero too, and that is checked rather than assumed.

**Claims.** The loan's contractual claim in hold year ``y`` is that year's debt
service, plus the remaining balance in the final year, when Anchor repays it at
the modeled sale. The cash available to it is the Unit's own pre-debt cash for
the same annual bucket -- ``AcquisitionResults.unlevered_cash_flows[y]``, which
includes the pre-debt sale cash in the final year -- and only its nonnegative
part. Another Unit's cash never reaches it; cross-collateralization is never
inferred. The loan states ``COMMON_EQUITY_CONTRIBUTION``, its frozen D6
treatment, so every claim is paid.
"""

from __future__ import annotations

from math import isfinite

from ..contracts import AcquisitionTerms
from ..engine.contracts import AcquisitionResults, ensure_finite
from .contracts import (
    LEGACY_ACQUISITION_LOAN_ID_PREFIX,
    LEGACY_ACQUISITION_LOAN_PRIORITY,
    MONTHS_PER_HOLD_YEAR,
    CapitalStructureError,
    ContractualClaim,
    FixedAmount,
    FundingEvent,
    HoldYearPeriod,
    LegacyAcquisitionLoan,
    PositionClass,
    PositionFee,
    PositionScope,
    ScopeKind,
    ShortfallResolution,
    UnitCashAuthority,
)


def legacy_acquisition_loan_id(unit_id: str) -> str:
    """The reserved, deterministic identity of ``unit_id``'s adapted loan."""

    return f"{LEGACY_ACQUISITION_LOAN_ID_PREFIX}{unit_id}"


def _require_coherent(unit_id: object, terms: object, results: object) -> None:
    """``CapitalStructureError`` unless ``results`` is a completed result that
    spans the hold ``terms`` state, with a coherent loan."""

    if not isinstance(unit_id, str) or unit_id.strip() == "":
        raise CapitalStructureError(f"A Unit is named by a nonblank unit_id; got {unit_id!r}.")
    if not isinstance(terms, AcquisitionTerms):
        raise CapitalStructureError(f"Unit {unit_id!r} needs its AcquisitionTerms; got {type(terms).__qualname__}.")
    if not isinstance(results, AcquisitionResults):
        raise CapitalStructureError(
            f"Unit {unit_id!r} needs its completed AcquisitionResults; got {type(results).__qualname__}."
        )
    hold_period = terms.hold_period
    if (
        len(results.annual_debt_service) != hold_period
        or len(results.levered_owner_cash_flow_by_year) != hold_period
        or len(results.unlevered_cash_flows) != hold_period + 1
        or len(results.levered_cash_flows) != hold_period + 1
    ):
        raise CapitalStructureError(
            f"Unit {unit_id!r}'s results do not span the {hold_period}-year hold its terms state."
        )
    if not isfinite(results.loan_amount) or results.loan_amount < 0.0:
        raise CapitalStructureError(f"Unit {unit_id!r}'s loan_amount {results.loan_amount!r} is not a loan.")
    if results.loan_amount == 0.0 and (
        results.financing_fee != 0.0
        or results.remaining_loan_balance != 0.0
        or any(debt_service != 0.0 for debt_service in results.annual_debt_service)
    ):
        raise CapitalStructureError(
            f"Unit {unit_id!r} has no acquisition loan, yet its results carry a financing fee, debt service "
            "or a loan balance."
        )


def adapt_legacy_acquisition_loan(
    *, unit_id: str, terms: AcquisitionTerms, results: AcquisitionResults
) -> LegacyAcquisitionLoan | None:
    """``unit_id``'s acquisition loan as its priority-1 senior debt, read off
    ``results``, or ``None`` when the Unit has no acquisition loan.

    ``terms`` supplies descriptive metadata and the modeled payoff month only.
    Raises ``CapitalStructureError`` for incoherent inputs."""

    _require_coherent(unit_id, terms, results)
    if results.loan_amount == 0.0:
        return None
    position_id = legacy_acquisition_loan_id(unit_id)
    return LegacyAcquisitionLoan(
        position_id=position_id,
        position_class=PositionClass.SENIOR_DEBT,
        scope=PositionScope(kind=ScopeKind.UNIT, unit_id=unit_id),
        priority=LEGACY_ACQUISITION_LOAN_PRIORITY,
        shortfall_resolution=ShortfallResolution.COMMON_EQUITY_CONTRIBUTION,
        funding=FundingEvent(
            event_id=f"{position_id}:funding",
            model_month=0,
            sequence=1,
            amount_rule=FixedAmount(amount=results.loan_amount),
        ),
        financing_fee=PositionFee(
            fee_id=f"{position_id}:financing-fee",
            description="Acquisition-loan financing fee",
            amount=results.financing_fee,
            model_month=0,
            sequence=2,
        ),
        loan_amount=results.loan_amount,
        annual_debt_service=results.annual_debt_service,
        remaining_loan_balance=results.remaining_loan_balance,
        modeled_payoff_month=MONTHS_PER_HOLD_YEAR * terms.hold_period,
        interest_rate=terms.interest_rate,
        amortization=terms.amortization,
        io_period=terms.io_period,
        hold_period=terms.hold_period,
    )


def legacy_acquisition_loan_claims(
    loan: LegacyAcquisitionLoan, *, cash_authority: UnitCashAuthority
) -> tuple[ContractualClaim, ...]:
    """The loan's contractual claim in each hold year, each with the eligible
    pre-debt cash of the loan's own Unit for that annual bucket.

    Claim ``y`` = debt service ``y``, plus the remaining balance when ``y`` is
    the final year. Eligible cash ``y`` = the nonnegative part of
    ``cash_authority.pre_acquisition_debt_cash_flows[y]``. The timing is honest:
    each claim is reported in its hold year, never in a fabricated month."""

    if cash_authority.unit_id != loan.scope.unit_id:
        raise CapitalStructureError(
            f"The claims of {loan.position_id!r} are met from its own Unit's cash, never from Unit "
            f"{cash_authority.unit_id!r}'s."
        )
    pre_debt = cash_authority.pre_acquisition_debt_cash_flows
    hold_period = loan.hold_period
    if len(pre_debt) != hold_period + 1 or len(loan.annual_debt_service) != hold_period:
        raise CapitalStructureError(f"{loan.position_id!r} and its Unit's cash do not span one hold.")
    claims: list[ContractualClaim] = []
    for year in range(1, hold_period + 1):
        due = loan.annual_debt_service[year - 1]
        if year == hold_period:
            due = ensure_finite(f"legacy_claim[{year}]", due + loan.remaining_loan_balance)
        available = pre_debt[year]
        claims.append(
            ContractualClaim(
                position_id=loan.position_id,
                scope=loan.scope,
                period=HoldYearPeriod(hold_year=year),
                claim_due=due,
                cash_available=available if available > 0.0 else 0.0,
                shortfall_resolution=loan.shortfall_resolution,
            )
        )
    return tuple(claims)
