"""Refinance & Capital Events V1 Stage 3 -- the refinance audit workbook's
source: eligibility, typed refusals, and every frozen figure the workbook is
built from.

Implements ``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Section 25.1
(the ratified Stage 3 export sub-contract). The workbook audits the selected
saved Analysis Variant of one Investment:

- **Only a refinance-bearing, fresh analysis.** The selected Strategy's
  resolved Capital Structure must configure at least one refinance, and the
  analysis the analyst ran must still be the current one: its structured
  source fingerprint must equal the fingerprint of the saved state now.
- **Refusal, never a partial audit.** Every configured refinance must have
  executed and Common Equity must be reported. Anything else is refused with a
  typed reason; nothing is produced partially.
- **Frozen inputs, live formulas.** This module reads accepted results only
  and freezes them: the refinance inputs, the dependency figures (the value an
  LTV constraint consumed, the forward NOI a DSCR constraint consumed, the
  continuing senior debt, the pre-debt cash authority and the provider cash of
  every position the refinance does not touch) and Anchor's own results for
  reconciliation. The workbook reproduces the refinance with Excel formulas.

It computes no application figure. The one comparison it makes -- that the
frozen dependencies reproduce Anchor's Common Equity series under the Section
17 INV-5 identity -- is a refusal check, like Excel Export 1's final-balance
check: an audit whose own dependencies could not reconcile would mislead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from ...analysis.strategy import BASE_SCENARIO_ID, BASE_STRATEGY_ID
from ...capital_structure.contracts import DebtTerms, PositionClass
from ...capital_structure.events import AuthoredPositionRef, CapitalStructureWithEvents, RefinanceCostKind
from ...capital_structure.refinance_contracts import (
    ConstraintKind,
    FixedCapOperands,
    MaxLtvOperands,
    MinDscrOperands,
    RefinanceStatus,
)
from ...engine.contracts import IrrStatus

#: Excel Export 1's layout limit, shared so every audit refuses the same way.
MAX_EXPORT_HOLD_PERIOD = 100

#: The Section 9.7 conservation tolerance ``1e-6 + 1e-12 x |x|``, for the one
#: refusal check this module makes.
_IDENTITY_ABSOLUTE = 1e-6
_IDENTITY_RELATIVE = 1e-12


class RefinanceAuditRefusalCode(Enum):
    """Stable wire tokens for every reason the refinance audit is refused."""

    INVESTMENT_NOT_FOUND = "investment_not_found"
    NO_REFINANCE = "no_refinance"
    ANALYSIS_MISSING = "analysis_missing"
    ANALYSIS_STALE = "analysis_stale"
    REFINANCE_UNAVAILABLE = "refinance_unavailable"
    ANALYSIS_INCONSISTENT = "analysis_inconsistent"
    HOLD_PERIOD_EXCEEDS_EXPORT_LIMIT = "hold_period_exceeds_export_limit"
    EXPORT_GENERATION_FAILED = "export_generation_failed"


class RefinanceAuditExportError(ValueError):
    """A typed refusal. ``message`` is written for the analyst: it says what to
    do, and never carries a path, an exception or an internal identifier."""

    def __init__(self, code: RefinanceAuditRefusalCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True, kw_only=True)
class FeeLine:
    description: str
    amount: float


@dataclass(frozen=True, slots=True, kw_only=True)
class RetiringLoanSource:
    """One loan a refinance repays, with the terms its payoff is rebuilt from
    and Anchor's own figures to reconcile against."""

    name: str
    #: ``True`` for a Unit's acquisition loan, whose schedule ends at its full
    #: amortization; ``False`` for an authored position with a legal maturity.
    acquisition_loan: bool
    principal: float
    closing_fees: tuple[FeeLine, ...]
    interest_rate: float
    amortization: int
    io_period: int
    maturity_month: int | None
    #: Anchor's figures.
    scheduled_payment_at_m: float
    payoff: float
    retiring_lender_fees: float
    provider_cash_flows: tuple[float, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplacementSource:
    name: str
    class_label: str
    interest_rate: float
    amortization: int
    io_period: int
    maturity_month: int
    lender_fees: tuple[FeeLine, ...]
    #: Anchor's figures.
    first_year_service: float
    provider_cash_flows: tuple[float, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class EventSource:
    """One executed refinance: its inputs, its dependency figures and every
    Anchor figure the workbook reconciles against."""

    label: str
    scope_name: str
    hold_year: int
    model_month: int
    forward_year: int
    fixed_cap: float | None
    max_ltv: float | None
    value: float | None
    value_label: str | None
    value_analyst_supplied: bool
    continuing_senior_balance: float | None
    min_dscr: float | None
    forward_noi: float | None
    continuing_senior_service: float | None
    retiring: tuple[RetiringLoanSource, ...]
    retiring_fee_lines: tuple[tuple[str, str, float], ...]
    third_party_costs: tuple[FeeLine, ...]
    replacement: ReplacementSource
    #: Anchor's results, by constraint token.
    capacities: dict[str, float]
    service_per_dollar: float | None
    gross_proceeds: float
    binding: tuple[str, ...]
    tie: bool
    payoffs_total: float
    replacement_lender_fees: float
    retiring_lender_fees: float
    third_party_costs_total: float
    net_event_cash: float
    direction: str
    achieved_ltv: float | None
    achieved_dscr: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class OtherProvider:
    """A position the refinance does not touch: its provider-sign annual cash,
    frozen from Anchor's accepted result."""

    name: str
    cash_flows: tuple[float, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ContinuingLoan:
    """A Unit's acquisition loan no refinance repays, from its accepted facts."""

    name: str
    loan_amount: float
    financing_fee: float
    annual_debt_service: tuple[float, ...]
    remaining_loan_balance: float


@dataclass(frozen=True, slots=True, kw_only=True)
class PartnerSource:
    name: str
    contributions: tuple[float, ...]
    distributions: tuple[float, ...]
    net_cash_flows: tuple[float, ...]
    irr: float | None
    irr_status: IrrStatus
    moic: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class RefinanceAuditSource:
    """Everything one refinance audit workbook is built from."""

    investment_id: str
    investment_name: str
    strategy_label: str
    scenario_label: str
    hold_period: int
    events: tuple[EventSource, ...]
    pre_debt_cash_flows: tuple[float, ...]
    continuing_loans: tuple[ContinuingLoan, ...]
    other_providers: tuple[OtherProvider, ...]
    #: Anchor's Common Equity after Capital Structure.
    common_cash_flows: tuple[float, ...]
    recurring_cash_flows: tuple[float, ...]
    event_cash_flows: tuple[float, ...]
    common_irr: float | None
    common_irr_status: IrrStatus
    equity_multiple: float | None
    total_equity_invested: float
    total_cash_returned: float
    total_profit: float
    #: The acquisition-financing reference (labelled, never a headline).
    reference_levered_irr: float | None
    reference_equity_multiple: float | None
    partners: tuple[PartnerSource, ...] | None
    structured_source_fingerprint: str
    generated_at: datetime
    anchor_version: str
    source_commit: str | None


def _refuse(code: RefinanceAuditRefusalCode, message: str) -> RefinanceAuditExportError:
    return RefinanceAuditExportError(code, message)


_CLASS_LABELS = {
    PositionClass.SENIOR_DEBT: "Senior Debt",
    PositionClass.MEZZANINE_DEBT: "Mezzanine Debt",
    PositionClass.PREFERRED_EQUITY: "Preferred Equity",
    PositionClass.COMMON_EQUITY: "Common Equity",
}


def _close(actual: float, expected: float) -> bool:
    return abs(actual - expected) <= _IDENTITY_ABSOLUTE + _IDENTITY_RELATIVE * abs(expected)


def _common_equity_reconciles(
    hold: int,
    pre_debt: tuple[float, ...],
    continuing: tuple[ContinuingLoan, ...],
    other_providers: tuple[OtherProvider, ...],
    event_sources: list[EventSource] | tuple[EventSource, ...],
    common_cash_flows: Any,
) -> bool:
    """INV-5 (Section 17): whether the frozen dependencies reproduce Anchor's
    Common Equity series, before an audit is laid beside it.

    A refusal check only -- the same convention as the accepted exports'
    ``_consistency_problems``. It answers yes or no; nothing it adds up is
    returned or written to the workbook."""

    for t in range(hold + 1):
        providers = 0.0
        for loan in continuing:
            providers += (
                loan.financing_fee - loan.loan_amount
                if t == 0
                else loan.annual_debt_service[t - 1] + (loan.remaining_loan_balance if t == hold else 0.0)
            )
        for provider in other_providers:
            providers += provider.cash_flows[t]
        third = 0.0
        for source in event_sources:
            providers += source.replacement.provider_cash_flows[t]
            for loan in source.retiring:
                providers += loan.provider_cash_flows[t]
            if t == source.hold_year:
                third += source.third_party_costs_total
        if not _close(pre_debt[t] - providers - third, common_cash_flows[t]):
            return False
    return True


def refinance_audit_source(
    investment_id: str,
    *,
    strategy_id: str = BASE_STRATEGY_ID,
    scenario_id: str = BASE_SCENARIO_ID,
    analysed_fingerprint: str | None,
    generated_at: datetime,
    anchor_version: str,
    source_commit: str | None,
    db_path: Path | None = None,
) -> RefinanceAuditSource:
    """The workbook source for one saved Analysis Variant, or a typed refusal."""

    from ...deals import store
    from ...deals.contracts import DealNotFoundError, InvestmentNotFoundError
    from ...deals.partnership_variants import analyze_partnership_variant
    from ...deals.refinance_integration import has_capital_events
    from ...deals.refinance_presentation import scope_name, unit_names_of
    from ...deals.structured_variants import analyze_structured_variant, resolve_variant_capital_structure

    try:
        resolved = resolve_variant_capital_structure(investment_id, strategy_id, db_path=db_path)
        investment = store.get_investment(investment_id, db_path=db_path)
    except (InvestmentNotFoundError, DealNotFoundError):
        raise _refuse(
            RefinanceAuditRefusalCode.INVESTMENT_NOT_FOUND,
            "This analysis could not be found. It may have been deleted; refresh and try again.",
        ) from None
    if not has_capital_events(resolved.capital_structure):
        raise _refuse(
            RefinanceAuditRefusalCode.NO_REFINANCE,
            "The selected Capital Structure configures no refinance, so there is nothing for the refinance audit to "
            "reproduce. Excel Exports 1-3 cover the acquisition analysis.",
        )
    if analysed_fingerprint is None or analysed_fingerprint.strip() == "":
        raise _refuse(
            RefinanceAuditRefusalCode.ANALYSIS_MISSING,
            "Run the structured analysis of the saved Capital Structure first, then export.",
        )

    analysis = analyze_structured_variant(investment_id, strategy_id, scenario_id, db_path=db_path)
    if analysis.structured_source_fingerprint != analysed_fingerprint:
        raise _refuse(
            RefinanceAuditRefusalCode.ANALYSIS_STALE,
            "The saved underwriting or capital structure changed after the analysis on screen ran. Run it again, "
            "then export.",
        )
    if analysis.hold_period > MAX_EXPORT_HOLD_PERIOD:
        raise _refuse(
            RefinanceAuditRefusalCode.HOLD_PERIOD_EXCEEDS_EXPORT_LIMIT,
            f"The audit workbook supports hold periods up to {MAX_EXPORT_HOLD_PERIOD} years.",
        )

    result = analysis.result
    common = result.common_equity
    events = tuple(getattr(result, "capital_events", ()))
    if any(event.status is not RefinanceStatus.EXECUTED for event in events):
        raise _refuse(
            RefinanceAuditRefusalCode.REFINANCE_UNAVAILABLE,
            "A refinance of the selected Capital Structure did not execute for this analysis, so its audit would be "
            "partial. Resolve the refinance's stated reason in Capital Structure, run the analysis again, then export.",
        )
    if common.cash_flows is None or common.irr_status is None:
        raise _refuse(
            RefinanceAuditRefusalCode.REFINANCE_UNAVAILABLE,
            "Common Equity is not reported for this analysis, so the cash it received around the refinance cannot be "
            "audited. Resolve the reason shown in Capital Structure, run the analysis again, then export.",
        )
    if None in (common.total_equity_invested, common.total_cash_returned, common.total_profit):
        raise _refuse(
            RefinanceAuditRefusalCode.ANALYSIS_INCONSISTENT,
            "This analysis reports a Common Equity cash flow without its totals, so no workbook is produced. Run the "
            "analysis again, then export.",
        )
    if any(position.status.value != "complete" for position in result.positions):
        raise _refuse(
            RefinanceAuditRefusalCode.REFINANCE_UNAVAILABLE,
            "A position of the selected Capital Structure is not fully settled for this analysis, so its audit would "
            "be partial. Resolve it in Capital Structure, run the analysis again, then export.",
        )

    structure = resolved.capital_structure
    assert isinstance(structure, CapitalStructureWithEvents)
    authored = {position.position_id: position for position in structure.positions}
    stated_events = {event.event_id: event for event in structure.events}
    returns = {position.position_id: position for position in result.positions}
    unit_names = unit_names_of(tuple(result.unit_ids), db_path=db_path)
    multi_unit = len(result.unit_ids) > 1
    valuation_labels = {
        timepoint.timepoint_id: timepoint.label
        for timepoint in store.list_valuation_timepoints(investment_id, db_path=db_path)
    }
    legacy = {loan.scope.unit_id: loan for loan in result.legacy_acquisition_loans}

    def legacy_name(unit_id: str | None) -> str:
        return f"Acquisition loan – {unit_names.get(unit_id or '', 'Unit')}" if multi_unit else "Acquisition loan"

    retired_legacy: set[str] = set()
    event_positions: set[str] = set()
    event_sources: list[EventSource] = []
    for event in events:
        stated = stated_events[event.event_id]
        assert event.bridge is not None and event.funding is not None and event.sizing is not None
        retiring: list[RetiringLoanSource] = []
        for payoff in event.payoffs or ():
            if isinstance(payoff.ref, AuthoredPositionRef):
                position = authored[payoff.ref.position_id]
                terms = position.terms
                assert isinstance(terms, DebtTerms)
                position_returns = returns[payoff.ref.position_id]
                event_positions.add(payoff.ref.position_id)
                retiring.append(
                    RetiringLoanSource(
                        name=position.name,
                        acquisition_loan=False,
                        principal=position_returns.funded_amount,
                        closing_fees=tuple(
                            FeeLine(description=fee.description, amount=fee.amount)
                            for fee in terms.fees
                            if fee.model_month == 0
                        ),
                        interest_rate=terms.interest_rate,
                        amortization=terms.amortization,
                        io_period=terms.io_period,
                        maturity_month=terms.maturity_month,
                        scheduled_payment_at_m=payoff.scheduled_payment_at_m,
                        payoff=payoff.payoff,
                        retiring_lender_fees=payoff.retiring_lender_fees,
                        provider_cash_flows=tuple(position_returns.annual_cash_flows or ()),
                    )
                )
            else:
                loan = legacy[payoff.ref.unit_id]
                retired_legacy.add(payoff.ref.unit_id)
                retiring.append(
                    RetiringLoanSource(
                        name=legacy_name(payoff.ref.unit_id),
                        acquisition_loan=True,
                        principal=loan.loan_amount,
                        closing_fees=(
                            FeeLine(description="Acquisition-loan financing fee", amount=loan.financing_fee.amount),
                        ),
                        interest_rate=loan.interest_rate,
                        amortization=loan.amortization,
                        io_period=loan.io_period,
                        maturity_month=None,
                        scheduled_payment_at_m=payoff.scheduled_payment_at_m,
                        payoff=payoff.payoff,
                        retiring_lender_fees=payoff.retiring_lender_fees,
                        provider_cash_flows=tuple(payoff.provider_cash_flows or ()),
                    )
                )

        replacement_position = authored[event.funding.position_id]
        replacement_terms = replacement_position.terms
        assert isinstance(replacement_terms, DebtTerms)
        event_positions.add(event.funding.position_id)
        names = {
            **{ref_name.position_id: authored[ref_name.position_id].name for ref_name in stated.retiring if isinstance(ref_name, AuthoredPositionRef)},
        }
        retiring_fee_lines = tuple(
            (
                line.description,
                names.get(getattr(line.recipient, "position_id", ""), legacy_name(getattr(line.recipient, "unit_id", None))),
                line.amount,
            )
            for line in stated.costs
            if line.kind is RefinanceCostKind.RETIRING_LENDER_FEE
        )
        third_party = tuple(
            FeeLine(description=line.description, amount=line.amount)
            for line in stated.costs
            if line.kind is RefinanceCostKind.THIRD_PARTY_COST
        )
        capacities: dict[str, float] = {}
        fixed = ltv = dscr = None
        for capacity in event.sizing.capacities:
            assert capacity.capacity is not None
            capacities[capacity.kind.value] = capacity.capacity
            if capacity.kind is ConstraintKind.FIXED_CAP and isinstance(capacity.operands, FixedCapOperands):
                fixed = capacity.operands
            elif capacity.kind is ConstraintKind.MAX_LTV and isinstance(capacity.operands, MaxLtvOperands):
                ltv = capacity.operands
            elif capacity.kind is ConstraintKind.MIN_DSCR and isinstance(capacity.operands, MinDscrOperands):
                dscr = capacity.operands
        value = event.value_dependency
        noi = event.noi_dependency
        event_sources.append(
            EventSource(
                label=event.label,
                scope_name=scope_name(event.scope, unit_names),
                hold_year=event.hold_year,
                model_month=event.model_month,
                forward_year=noi.forward_year if noi is not None else event.hold_year,
                fixed_cap=None if fixed is None else fixed.amount,
                max_ltv=None if ltv is None else ltv.max_ltv,
                value=None if ltv is None else ltv.scope_value,
                value_label=None if value is None else valuation_labels.get(value.timepoint_id),
                value_analyst_supplied=bool(value is not None and value.analyst_supplied),
                continuing_senior_balance=None if ltv is None else ltv.continuing_senior_balance,
                min_dscr=None if dscr is None else dscr.min_dscr,
                forward_noi=None if dscr is None else dscr.forward_noi,
                continuing_senior_service=None if dscr is None else dscr.continuing_senior_service,
                retiring=tuple(retiring),
                retiring_fee_lines=retiring_fee_lines,
                third_party_costs=third_party,
                replacement=ReplacementSource(
                    name=replacement_position.name,
                    class_label=_CLASS_LABELS[replacement_position.position_class],
                    interest_rate=replacement_terms.interest_rate,
                    amortization=replacement_terms.amortization,
                    io_period=replacement_terms.io_period,
                    maturity_month=replacement_terms.maturity_month,
                    lender_fees=tuple(FeeLine(description=fee.description, amount=fee.amount) for fee in replacement_terms.fees),
                    first_year_service=event.funding.first_year_service,
                    provider_cash_flows=tuple(returns[event.funding.position_id].annual_cash_flows or ()),
                ),
                capacities=capacities,
                service_per_dollar=None if dscr is None else dscr.first_year_service_per_dollar,
                gross_proceeds=event.bridge.gross_proceeds,
                binding=tuple(kind.value for kind in event.sizing.binding),
                tie=event.sizing.tie,
                payoffs_total=event.bridge.payoffs,
                replacement_lender_fees=event.bridge.replacement_lender_fees,
                retiring_lender_fees=event.bridge.retiring_lender_fees,
                third_party_costs_total=event.bridge.third_party_costs,
                net_event_cash=event.bridge.net_event_cash,
                direction=event.bridge.direction.value,
                achieved_ltv=event.funding.achieved_ltv,
                achieved_dscr=event.funding.achieved_dscr,
            )
        )

    other_providers = tuple(
        OtherProvider(name=position.name, cash_flows=tuple(position.annual_cash_flows or ()))
        for position in result.positions
        if position.position_id not in event_positions and position.position_class is not PositionClass.COMMON_EQUITY
    )
    continuing = tuple(
        ContinuingLoan(
            name=legacy_name(loan.scope.unit_id),
            loan_amount=loan.loan_amount,
            financing_fee=loan.financing_fee.amount,
            annual_debt_service=tuple(loan.annual_debt_service),
            remaining_loan_balance=loan.remaining_loan_balance,
        )
        for loan in result.legacy_acquisition_loans
        if loan.scope.unit_id not in retired_legacy
    )

    # The pre-debt authority and the acquisition-financing reference.
    if investment.hidden:
        from ...deals.variants import analyze_variant

        variant = analyze_variant(investment_id, strategy_id, scenario_id, db_path=db_path)
        economics = getattr(variant.results, "results", variant.results)
        name = store.get_deal(result.unit_ids[0], db_path=db_path).name
    else:
        from ...deals.investment_variants import analyze_investment_variant

        variant = analyze_investment_variant(investment_id, strategy_id, scenario_id, db_path=db_path)
        economics = variant.consolidated_results
        name = store.get_visible_investment(investment_id, db_path=db_path).name
    pre_debt = tuple(economics.unlevered_cash_flows)

    hold = analysis.hold_period
    if not _common_equity_reconciles(hold, pre_debt, continuing, other_providers, event_sources, common.cash_flows):
        raise _refuse(
            RefinanceAuditRefusalCode.ANALYSIS_INCONSISTENT,
            "The refinance audit could not reconcile this analysis's Common Equity cash flow from its accepted "
            "dependencies, so no workbook is produced. Run the analysis again; if this persists, the structure "
            "is outside what the audit reproduces.",
        )

    partners: tuple[PartnerSource, ...] | None = None
    try:
        partnership = analyze_partnership_variant(investment_id, strategy_id, scenario_id, db_path=db_path)
    except Exception:  # noqa: BLE001 -- no Partnership, or one that does not run: no partner audit
        partnership = None
    if partnership is not None and partnership.result is not None and partnership.result.partners is not None:
        stated_partners = {partner.partner_id: partner.name for partner in partnership.partnership.partners}
        partners = tuple(
            PartnerSource(
                name=stated_partners.get(partner.partner_id, "Partner"),
                contributions=tuple(partner.contributions),
                distributions=tuple(partner.distributions),
                net_cash_flows=tuple(partner.net_cash_flows),
                irr=partner.irr,
                irr_status=partner.irr_status,
                moic=partner.moic,
            )
            for partner in partnership.result.partners
        )

    strategy_label = "Base Strategy"
    if strategy_id != BASE_STRATEGY_ID:
        strategy_label = store.get_strategy(investment_id, strategy_id, db_path=db_path).strategy.name
    scenario_label = "Base Scenario"
    if scenario_id != BASE_SCENARIO_ID:
        scenario_label = store.get_scenario(investment_id, scenario_id, db_path=db_path).scenario.name

    return RefinanceAuditSource(
        investment_id=investment_id,
        investment_name=name,
        strategy_label=strategy_label,
        scenario_label=scenario_label,
        hold_period=hold,
        events=tuple(event_sources),
        pre_debt_cash_flows=pre_debt,
        continuing_loans=continuing,
        other_providers=other_providers,
        common_cash_flows=tuple(common.cash_flows),
        recurring_cash_flows=tuple(common.recurring_cash_flows),
        event_cash_flows=tuple(common.event_cash_flows),
        common_irr=common.irr,
        common_irr_status=common.irr_status,
        equity_multiple=common.equity_multiple,
        total_equity_invested=common.total_equity_invested,
        total_cash_returned=common.total_cash_returned,
        total_profit=common.total_profit,
        reference_levered_irr=getattr(economics, "levered_irr", None),
        reference_equity_multiple=getattr(economics, "equity_multiple", None),
        partners=partners,
        structured_source_fingerprint=analysis.structured_source_fingerprint,
        generated_at=generated_at,
        anchor_version=anchor_version,
        source_commit=source_commit,
    )


__all__ = [
    "ContinuingLoan",
    "EventSource",
    "FeeLine",
    "MAX_EXPORT_HOLD_PERIOD",
    "OtherProvider",
    "PartnerSource",
    "RefinanceAuditExportError",
    "RefinanceAuditRefusalCode",
    "RefinanceAuditSource",
    "ReplacementSource",
    "RetiringLoanSource",
    "refinance_audit_source",
]
