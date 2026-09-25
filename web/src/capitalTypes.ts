/**
 * Phase 7 Gate P7.8B -- the typed wire contracts of the Capital Structure API.
 *
 * Mirrors, field for field, what `src/anchor/api.py` returns for the persisted
 * Capital Structure, the structured variant analysis, the Position perspectives
 * and the POSITION Decision Matrix. Nothing here computes, resolves or validates
 * anything: the P7.7 validator decides what a structure may say, and the P7.8A
 * executor produces every number a position leads to.
 *
 * **Every typed variant carries its `kind`.** A funding rule and a position's
 * terms are unions, and JSON cannot tell a union member apart by its fields, so
 * the backend sends an explicit discriminator and this file reads it. Nothing is
 * inferred from which fields happen to be present.
 *
 * **Two layers of identity.** `project_source_fingerprint` is the Project
 * variant's own, unchanged by any structure; `structured_source_fingerprint` is
 * that fingerprint plus the resolved structure's economics -- and *is* it when
 * the structure is empty.
 */

import type { IrrStatus } from './types';

// =============================================================================
// The authored contract
// =============================================================================

/** Mirrors `PositionClass`. */
export type PositionClass = 'senior_debt' | 'mezzanine_debt' | 'preferred_equity' | 'common_equity';

/** Mirrors `ScopeKind`: one Unit, or the whole Investment. */
export type ScopeKind = 'unit' | 'investment';

/** Mirrors `ShortfallResolution`. There is no default: a claim-bearing position
 * always states one. */
export type ShortfallResolution = 'common_equity_contribution' | 'unresolved';

/** Mirrors `AccrualConvention`. Never assumed; stated only when accrual is
 * permitted. */
export type AccrualConvention = 'simple' | 'annual_compound';

/** Mirrors `PositionScope`: `unit` carries exactly one `unit_id`, `investment`
 * carries none. */
export interface PositionScope {
  kind: ScopeKind;
  unit_id: string | null;
}

/** Mirrors the funding amount rules. P7.8B authors the first two; `pct_of_value`
 * is representable because the contract is, and the routes refuse it until
 * valuation timepoints exist. */
export type FundingAmountRule =
  | { kind: 'fixed_amount'; amount: number }
  | { kind: 'pct_of_price'; pct: number }
  | { kind: 'pct_of_value'; timepoint_id: string; pct: number }
  | CapitalEventProceeds;

/** Refinance & Capital Events V1 Stage 3 -- mirrors `RefinanceProceeds`: the
 * one funding rule of a replacement position, whose amount is the gross
 * proceeds the named capital event sizes. It carries no amount of its own. */
export interface CapitalEventProceeds {
  kind: 'refinance_proceeds';
  capital_event_id: string;
}

/** Mirrors `FundingEvent`. P7.8 funds at closing (`model_month` 0); `sequence`
 * orders events that share a month. */
export interface FundingEvent {
  event_id: string;
  model_month: number;
  sequence: number;
  amount_rule: FundingAmountRule;
}

/** Mirrors `PositionFee`. A fee is a receipt to the position and a Common
 * Equity use; it never changes the funded amount. */
export interface PositionFee {
  fee_id: string;
  description: string;
  amount: number;
  model_month: number;
  sequence: number;
}

/** Mirrors `DebtTerms`. P7.8 debt is cash pay: `current_pay_rate` is the whole
 * `interest_rate` and `pik_rate` is 0. */
export interface DebtTerms {
  kind: 'debt';
  interest_rate: number;
  amortization: number;
  io_period: number;
  maturity_month: number;
  fees: PositionFee[];
  current_pay_rate: number;
  pik_rate: number;
}

/** Mirrors `PreferredEquityTerms`. */
export interface PreferredEquityTerms {
  kind: 'preferred_equity';
  preferred_rate: number;
  current_pay_rate: number;
  accrual_permitted: boolean;
  accrual_convention: AccrualConvention | null;
  redemption_month: number;
}

export type PositionTerms = DebtTerms | PreferredEquityTerms;

/** Mirrors `CapitalPosition`. Common equity carries no terms, no funding and no
 * resolution: it names the residual. */
export interface CapitalPosition {
  position_id: string;
  name: string;
  position_class: PositionClass;
  priority: number;
  scope: PositionScope;
  funding: FundingEvent[];
  terms: PositionTerms | null;
  shortfall_resolution: ShortfallResolution | null;
}

/** Mirrors `CapitalStructure`. The empty structure is today's behaviour: each
 * Unit's acquisition loan and the residual (P-11). */
export interface CapitalStructure {
  positions: CapitalPosition[];
  /** Refinance & Capital Events V1: present only when the structure states at
   * least one capital event. Absent is the empty set, and a structure with none
   * travels exactly as it always did. */
  capital_events?: CapitalEvent[];
}

/** `GET`/`PUT /deals/{id}/capital-structure`. A standalone Deal reports no
 * Investment; reading creates neither. */
export interface DealCapitalStructure {
  deal_id: string;
  investment_id: string | null;
  capital_structure: CapitalStructure;
}

/** `GET`/`PUT /investments/{id}/capital-structure`. */
export interface InvestmentCapitalStructure {
  investment_id: string;
  capital_structure: CapitalStructure;
}

/** One entry of a structured 422: the P7.7 contract issues, the P7.8A execution
 * issues and the identity conflicts all arrive in this shape. */
export interface CapitalStructureIssue {
  code: string;
  message: string;
  position_id: string | null;
  field: string | null;
}

// =============================================================================
// The result
// =============================================================================

/** Mirrors `PositionResultStatus`. */
export type PositionResultStatus =
  | 'complete'
  | 'unresolved_funding'
  | 'blocked_by_senior_unresolved'
  | 'refinance_unavailable';

/** Mirrors `CapitalStructureStatus`. */
export type CapitalStructureStatus = 'complete' | 'unresolved_funding' | 'refinance_unavailable';

/** Mirrors `PositionUnavailableReason`. */
export type PositionUnavailableReason =
  | 'unresolved_funding_requirement'
  | 'senior_unresolved_funding_requirement'
  | 'refinance_unavailable';

/** Mirrors `PriceBasis`: the acquisition price a loan-to-price is measured
 * against -- never an as-is, stabilized or market value. */
export interface PriceBasis {
  kind: 'unit_purchase_price' | 'investment_transaction_price';
  amount: number;
}

/** Mirrors `ResolvedFundingEvent`: one authored event resolved to dollars. */
export interface ResolvedFundingEvent {
  event_id: string;
  model_month: number;
  sequence: number;
  amount_rule: FundingAmountRule;
  price_basis: PriceBasis | null;
  amount: number;
}

/** Mirrors `PositionCashFlowEvent`, from the provider's side: funding negative,
 * receipts positive. */
export interface PositionCashFlowEvent {
  event_id: string;
  position_id: string;
  model_month: number;
  sequence: number;
  kind:
    | 'funding'
    | 'fee'
    | 'scheduled_debt_service'
    | 'balloon'
    | 'preferred_current_pay'
    | 'preferred_redemption'
    | 'refinance_payoff'
    | 'refinance_funding';
  amount: number;
}

/** Mirrors `ClaimPeriod`: an exact model month, or an annual availability
 * bucket. The `kind` says which. */
export type ClaimPeriod = { kind: 'model_month'; model_month: number } | { kind: 'hold_year'; hold_year: number };

/** Mirrors `FundingRequirement`: a contractual claim the eligible cash could not
 * meet. It is not the D6 Net Additional Equity Requirement. */
export interface FundingRequirement {
  requirement_id: string;
  position_id: string;
  scope: PositionScope;
  period: ClaimPeriod;
  claim_amount: number;
  cash_available: number;
  claim_paid_from_cash: number;
  amount: number;
  equity_contribution: number;
  unpaid_claim_amount: number;
  resolution: ShortfallResolution;
  status: 'resolved' | 'unresolved';
  explanation: string;
}

/** Mirrors `DebtPositionSchedule`. `maturity_month` is the legal maturity;
 * `modeled_payoff_month` is the earliest modeled extinguishment. */
export interface DebtPositionSchedule {
  principal: number;
  interest_rate: number;
  monthly_rate: number;
  n_payments: number;
  io_months: number;
  io_payment: number;
  amortizing_payment: number;
  maturity_month: number;
  scheduled_full_amortization_month: number;
  modeled_payoff_month: number;
  balance_at_payoff: number;
}

export interface PreferredAccrualYear {
  hold_year: number;
  unreturned_principal: number;
  current_pay: number;
  beginning_accrued: number;
  accrual: number;
  ending_accrued: number;
}

export interface PreferredPositionSchedule {
  principal: number;
  preferred_rate: number;
  current_pay_rate: number;
  accrual_rate: number;
  accrual_convention: AccrualConvention | null;
  redemption_month: number;
  modeled_payoff_month: number;
  years: PreferredAccrualYear[];
  balance_at_redemption: number;
}

/** Mirrors `PositionReturns`.
 *
 * **Returns** (`annual_cash_flows` through `profit`) are reported only for a
 * `complete` position; otherwise they are `null` with `unavailable_reason`.
 * **Structural metrics** (`attachment_basis` through `minimum_coverage`) are
 * contractual underwriting facts and stand whatever the cash settlement did --
 * a distinction the UI must keep. */
export interface PositionReturns {
  position_id: string;
  name: string;
  position_class: PositionClass;
  scope: PositionScope;
  priority: number;
  status: PositionResultStatus;
  unavailable_reason: PositionUnavailableReason | null;
  unavailable_message: string | null;
  blocking_requirement_ids: string[];

  funding: ResolvedFundingEvent[];
  funded_amount: number;
  debt_schedule: DebtPositionSchedule | null;
  preferred_schedule: PreferredPositionSchedule | null;
  modeled_payoff_month: number;
  balance_at_maturity_or_exit: number;
  cash_flow_events: PositionCashFlowEvent[];
  funding_requirements: FundingRequirement[];

  annual_cash_flows: number[] | null;
  irr: number | null;
  irr_status: IrrStatus | null;
  total_cash_received: number | null;
  moic: number | null;
  profit: number | null;

  valuation_basis: PriceBasis;
  attachment_basis: number;
  detachment_basis: number;
  last_dollar_basis: number;
  attachment_ltv: number | null;
  detachment_ltv: number | null;
  debt_yield_through: number | null;
  coverage_by_year: (number | null)[];
  headline_coverage: number | null;
  minimum_coverage: number | null;
}

/** Mirrors `CommonEquityReturns`: the residual after every executable claim.
 * These are the Common Equity figures after structured capital -- never the
 * project's levered returns, which still exist and still differ (NS-1). */
export interface CommonEquityReturns {
  position_id: string | null;
  scope: PositionScope;
  status: CapitalStructureStatus;
  cash_flows: number[] | null;
  unavailable_reason: 'unresolved_funding_requirement' | 'refinance_unavailable' | null;
  unavailable_message: string | null;
  irr: number | null;
  irr_status: IrrStatus | null;
  equity_multiple: number | null;
  total_equity_invested: number | null;
  total_cash_returned: number | null;
  total_profit: number | null;
  /** Refinance & Capital Events V1: present only for a refinance-bearing
   * result. `cash_flows` is `recurring_cash_flows` plus `event_cash_flows`,
   * each supplied by the engine; all three are `null` together when Common
   * Equity is unavailable. */
  recurring_cash_flows?: number[] | null;
  event_cash_flows?: number[] | null;
}

/** Mirrors `LegacyAcquisitionLoan`: each Unit's existing acquisition loan, read
 * off its completed results. Shown read-only: it is not authored here and is
 * never recreated. */
export interface LegacyAcquisitionLoan {
  position_id: string;
  position_class: PositionClass;
  scope: PositionScope;
  priority: number;
  shortfall_resolution: ShortfallResolution;
  loan_amount: number;
  annual_debt_service: number[];
  remaining_loan_balance: number;
  modeled_payoff_month: number;
  interest_rate: number;
  amortization: number;
  io_period: number;
  hold_period: number;
}

/** Mirrors `StructuredCapitalResult`. */
export interface StructuredCapitalResult {
  analysis_scope: ScopeKind;
  unit_ids: string[];
  hold_period: number;
  status: CapitalStructureStatus;
  legacy_acquisition_loans: LegacyAcquisitionLoan[];
  positions: PositionReturns[];
  funding_requirements: FundingRequirement[];
  common_equity: CommonEquityReturns;
  /** Refinance & Capital Events V1: present only when the resolved structure
   * states capital events. One result per event, in economic order. */
  capital_events?: RefinanceResult[];
  /** The replacement of each event that did not execute: it has no schedule,
   * so it is never among `positions` with invented zeros. */
  unexecuted_positions?: UnexecutedPosition[];
}

/** Which root executed the structure. A hidden one-unit Investment is still
 * called a Deal on screen. */
export type StructuredRootKind = 'hidden_unit' | 'visible_investment';

/** Which owner stated the structure this variant ran. */
export type CapitalStructureSource = 'base' | 'strategy';

/** `GET /investments/{id}/structured-variants/{strategy}/{scenario}/fingerprint`. */
export interface StructuredVariantFingerprint {
  investment_id: string;
  strategy_id: string;
  scenario_id: string;
  root_kind: StructuredRootKind;
  unit_ids: string[];
  capital_structure: CapitalStructure;
  capital_structure_source: CapitalStructureSource;
  project_source_fingerprint: string;
  structured_source_fingerprint: string;
}

/** `POST /investments/{id}/structured-variants/{strategy}/{scenario}/analysis`.
 * `project_cache_status` is operational metadata about the Project half only;
 * the structured half is always recomputed. */
export interface StructuredVariantAnalysis {
  investment_id: string;
  strategy_id: string;
  scenario_id: string;
  root_kind: StructuredRootKind;
  unit_ids: string[];
  hold_period: number;
  capital_structure: CapitalStructure;
  capital_structure_source: CapitalStructureSource;
  project_source_fingerprint: string;
  structured_source_fingerprint: string;
  project_cache_status: string;
  result: StructuredCapitalResult;
  /** Refinance & Capital Events V1: the server's typed statement of which
   * return namespace is primary. Present only for a refinance-bearing
   * variant. */
  primary_return?: PrimaryReturnView;
}

// =============================================================================
// The POSITION perspective
// =============================================================================

/** One addressable `POSITION(position_id)` perspective: the union of the ids
 * the Base structure and every Strategy's own hold. */
export interface PositionPerspective {
  position_id: string;
  name: string;
  position_class: PositionClass;
  scope: PositionScope;
  is_common_equity_marker: boolean;
  present_in_base: boolean;
  strategy_ids: string[];
}

/** `GET /investments/{id}/position-perspectives`. */
export interface PositionPerspectives {
  investment_id: string;
  positions: PositionPerspective[];
}

/** Whether the selected position took part in one cell. */
export type PositionApplicability = 'present' | 'not_present' | 'not_analysed';

/** One Strategy x Scenario cell of a Position matrix. */
export interface PositionDecisionCell {
  strategy_id: string;
  scenario_id: string;
  status: 'valid' | 'invalid';
  applicability: PositionApplicability;
  issues: { source: string; code: string; message: string; field: string | null }[];
  project_source_fingerprint: string | null;
  source_fingerprint: string | null;
  hold_period: number | null;
  position_status: PositionResultStatus | null;
  unavailable_reason: PositionUnavailableReason | null;
  unavailable_message: string | null;
  metrics: {
    metric: string;
    value: number | null;
    irr_status: IrrStatus | null;
    reason: string | null;
    message: string | null;
  }[];
  deltas: {
    metric: string;
    value: number | null;
    is_baseline: boolean;
    reason: string | null;
    message: string | null;
  }[];
}

/** The Position comparison package. Its `matrix_fingerprint` includes the
 * selected position and every cell's structured fingerprint, so two positions
 * over the same variants never share one. */
export interface PositionDecisionMatrix {
  perspective: 'position';
  position_id: string;
  position_name: string;
  position_class: PositionClass;
  scope: PositionScope;
  is_common_equity_marker: boolean;
  strategies: { strategy_id: string; name: string; is_base: boolean; hold_period: number | null }[];
  scenarios: { scenario_id: string; name: string; is_base: boolean }[];
  metrics: {
    metric: string;
    label: string;
    unit: 'rate' | 'multiple' | 'currency';
    direction: 'higher_is_better' | 'lower_is_better';
    horizon_dependent: boolean;
  }[];
  omitted_metrics: { metric: string; reason: string; message: string }[];
  hold_periods: number[];
  cross_scenario_figures: boolean;
  cells: PositionDecisionCell[];
  strategy_figures: {
    strategy_id: string;
    worst_cases: {
      metric: string;
      direction: 'higher_is_better' | 'lower_is_better';
      value: number | null;
      scenario_id: string | null;
      scenario_name: string | null;
      reason: string | null;
      message: string | null;
    }[];
    ranges: {
      metric: string;
      minimum: number | null;
      maximum: number | null;
      spread: number | null;
      reason: string | null;
      message: string | null;
    }[];
  }[];
  matrix_fingerprint: string | null;
  matrix_fingerprint_reason: string | null;
}

/** `POST /investments/{id}/position-decision-matrix/{position_id}`. */
export interface PositionDecisionMatrixReport {
  investment_id: string;
  root_kind: StructuredRootKind;
  unit_ids: string[];
  position: PositionPerspective;
  matrix: PositionDecisionMatrix;
}
// =============================================================================
// Refinance & Capital Events V1 Stage 3 -- the capital-event wire contracts
//
// Mirrors `anchor.capital_structure.events` and `refinance_contracts`, field
// for field. Nothing here sizes, amortizes, nets or compares: capacities, the
// binding set, payoffs, fees, the bridge and every Common Equity figure are the
// accepted engine's, carried through unchanged.
// =============================================================================

/** Mirrors `RetiringPositionRef`: an authored debt position by its id, or a
 * Unit's acquisition loan by its Unit -- never by a reserved identity string. */
export type RetiringPositionRef =
  | { kind: 'authored_position'; position_id: string }
  | { kind: 'legacy_acquisition_loan'; unit_id: string };

/** Mirrors `RefinanceSizing`: an absent constraint is disabled and states no
 * target. At least one is present. */
export interface RefinanceSizing {
  fixed_cap: { amount: number } | null;
  max_ltv: { max_ltv: number } | null;
  min_dscr: { min_dscr: number } | null;
}

export type RefinanceCostKind = 'retiring_lender_fee' | 'third_party_cost';

/** Mirrors `RefinanceCostLine`: one fixed-dollar event cost. A retiring
 * lender fee names its recipient; a third-party cost names none. */
export interface RefinanceCostLine {
  cost_id: string;
  kind: RefinanceCostKind;
  amount: number;
  recipient: RetiringPositionRef | null;
  description: string;
}

/** Mirrors `RefinanceEvent`. `label` is presentation only; `event_id` is the
 * identity. */
export interface CapitalEvent {
  event_id: string;
  kind: 'refinance';
  scope: PositionScope;
  timing: { model_month: number; sequence: number };
  label: string;
  retiring: RetiringPositionRef[];
  replacement_position_id: string;
  sizing: RefinanceSizing;
  /** Required exactly when `max_ltv` is present, and refused otherwise. */
  valuation: { timepoint_id: string } | null;
  costs: RefinanceCostLine[];
}

export type RefinanceStatus = 'executed' | 'unavailable' | 'not_executable' | 'blocked';

export type RefinanceUnavailableReason =
  | 'event_outside_hold_horizon'
  | 'timepoint_not_found'
  | 'model_month_mismatch'
  | 'scope_not_covered'
  | 'valuation_unavailable'
  | 'evidence_not_approved'
  | 'forward_noi_unavailable'
  | 'non_positive_forward_noi'
  | 'retiring_position_absent'
  | 'retiring_position_not_outstanding'
  | 'non_positive_capacity'
  | 'upstream_unresolved_funding'
  | 'upstream_capital_event_not_executed';

export type ConstraintKind = 'fixed_cap' | 'max_ltv' | 'min_dscr';

/** The three operand shapes are told apart by their capacity's `kind`; they
 * carry no discriminator of their own. */
export interface FixedCapOperands {
  amount: number;
}

export interface MaxLtvOperands {
  max_ltv: number;
  scope_value: number | null;
  continuing_senior_balance: number;
}

export interface MinDscrOperands {
  min_dscr: number;
  forward_noi: number | null;
  continuing_senior_service: number;
  service_capacity: number | null;
  first_year_service_per_dollar: number;
}

/** Mirrors `ConstraintCapacity`. `capacity` is `null` exactly when the
 * constraint is unavailable; a computed capacity may be zero or negative. */
export interface ConstraintCapacity {
  kind: ConstraintKind;
  status: 'available' | 'unavailable';
  capacity: number | null;
  operands: FixedCapOperands | MaxLtvOperands | MinDscrOperands;
  unavailable_reason: RefinanceUnavailableReason | null;
  unavailable_message: string | null;
}

export interface SizingOutcome {
  capacities: ConstraintCapacity[];
  gross_proceeds: number | null;
  binding: ConstraintKind[];
  tie: boolean;
}

/** Mirrors `ValueDependency`: present only when LTV is enabled. */
export interface ValueDependency {
  timepoint_id: string;
  scope: PositionScope;
  model_month: number;
  method: string | null;
  analyst_supplied: boolean | null;
  status: 'available' | 'unavailable';
  value: number | null;
  valuation_unavailable_reason: string | null;
}

/** Mirrors `NoiDependency`: present only when DSCR is enabled. */
export interface NoiDependency {
  scope: PositionScope;
  model_month: number;
  forward_year: number;
  status: 'available' | 'unavailable';
  forward_noi: number | null;
}

export interface RetiringPayoff {
  ref: RetiringPositionRef;
  /** Internal identity; never shown. The position is named from `ref`. */
  position_id: string;
  scheduled_payment_at_m: number;
  payoff: number;
  payoff_authority: 'authored_schedule' | 'acquisition_debt_balance_service';
  retiring_lender_fees: number;
  provider_cash_flows: number[] | null;
}

export interface ReplacementFunding {
  position_id: string;
  funding_month: number;
  gross_proceeds: number;
  replacement_lender_fees: number;
  first_service_month: number;
  first_year_service: number;
  achieved_ltv: number | null;
  achieved_dscr: number | null;
}

/** Mirrors `RefinanceBridge`: the event audit bridge, every line the
 * engine's own. */
export interface RefinanceBridge {
  gross_proceeds: number;
  payoffs: number;
  replacement_lender_fees: number;
  retiring_lender_fees: number;
  third_party_costs: number;
  net_event_cash: number;
  direction: 'distribution' | 'contribution' | 'zero';
}

export interface RefinanceResult {
  event_id: string;
  kind: 'refinance';
  label: string;
  scope: PositionScope;
  model_month: number;
  hold_year: number;
  status: RefinanceStatus;
  value_dependency: ValueDependency | null;
  noi_dependency: NoiDependency | null;
  sizing: SizingOutcome | null;
  payoffs: RetiringPayoff[] | null;
  funding: ReplacementFunding | null;
  bridge: RefinanceBridge | null;
  unavailable_reason: RefinanceUnavailableReason | null;
  unavailable_message: string | null;
}

export interface UnexecutedPosition {
  position_id: string;
  name: string;
  position_class: PositionClass;
  scope: PositionScope;
  priority: number;
  event_id: string;
  unavailable_reason: PositionUnavailableReason;
  unavailable_message: string;
}

export type ReturnNamespace =
  | 'common_equity_after_capital_structure'
  | 'partner'
  | 'acquisition_financing_reference';

/** Mirrors `PrimaryReturnView`: which namespace is primary for a
 * refinance-bearing variant. The frontend decides nothing economically. */
export interface PrimaryReturnView {
  primary_equity_namespace: ReturnNamespace;
  primary_investor_namespace: ReturnNamespace | null;
  reference_namespace: ReturnNamespace;
  reference_excludes_capital_events: boolean;
  status: 'available' | 'unavailable';
  unavailable_reason: string | null;
  unavailable_message: string | null;
  capital_event_ids: string[];
  executed_event_ids: string[];
}

/** `GET /investments/{id}/capital-event-presence`: whether each Strategy's
 * resolved Capital Structure configures a capital event. `strategy_id` is the
 * reserved Base key for the Base Strategy. */
export interface CapitalEventPresence {
  investment_id: string;
  strategies: { strategy_id: string; capital_events_configured: boolean }[];
  /** The Project matrix metrics that are the acquisition-financing reference
   * beside a refinance-bearing Strategy. The server decides them. */
  acquisition_financing_metrics: string[];
}
