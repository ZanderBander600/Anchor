/**
 * Phase 7 Gate P7.6 -- the typed wire contracts of the visible Investment.
 *
 * Mirrors, field for field, what `src/anchor/api.py` returns for the P7.6
 * routes: the visible Investment and its lifecycle (`anchor.deals.contracts.
 * VisibleInvestment`, `anchor.investment.contracts`), its consolidated variant
 * analysis (`anchor.deals.investment_variants.InvestmentVariantAnalysis` over
 * `anchor.consolidation.contracts.ConsolidatedResults`) and its Decision Matrix
 * (`anchor.deals.decision_matrix.InvestmentDecisionMatrixReport`).
 *
 * **Every number is the backend's.** The allocated purchase price, the
 * allocation variance, every consolidated series and every return metric are
 * fields of these responses. The frontend formats them; it sums, subtracts,
 * averages and derives nothing (P-5, Q22).
 *
 * **Reporting metadata stays reporting metadata.** `unit_kind`, a membership's
 * `label` and `ordinal`, and a transaction cost's `description` and `category`
 * never reach a calculation on the backend, and nothing here branches on them.
 */

import type { BusinessPlanInput } from './businessPlan';
import type { DecisionMatrix } from './decisionTypes';
import type { LeaseLevelAcquisitionResults } from './leaseLevelTypes';
import type { VariantCacheStatus } from './scenarioTypes';
import type { AcquisitionResults, DetailedAcquisitionResults, IrrStatus, OperatingMode } from './types';

/** Mirrors `UnitKind`: what a Unit is to its Investment. Reporting only. */
export type UnitKind = 'property' | 'component' | 'phase';

/** Mirrors `TransactionCostCategory`. Reporting only; financing fees are
 * deliberately not a member. */
export type TransactionCostCategory =
  | 'acquisition_fee'
  | 'due_diligence'
  | 'legal'
  | 'portfolio_transaction_cost'
  | 'other';

/** Mirrors `InvestmentUnitMembership`. `unit_id` is the existing Deal's id. */
export interface InvestmentUnitMembership {
  unit_id: string;
  ordinal: number;
  label: string | null;
  unit_kind: UnitKind;
  acquisition_month: number;
  disposition_month: number | null;
}

/** Mirrors `InvestmentTransactionCost`: one Investment-level closing use.
 * `model_month` is always 0 (closing) in P7.6. */
export interface InvestmentTransactionCost {
  cost_id: string;
  description: string;
  category: TransactionCostCategory;
  amount: number;
  model_month: number;
}

/** Mirrors `VisibleInvestment`. `transaction_price` is reconciliation and
 * reporting only: it never enters a cash flow. */
export interface VisibleInvestment {
  id: string;
  name: string;
  transaction_price: number;
  units: InvestmentUnitMembership[];
  business_plan: BusinessPlanInput;
  transaction_costs: InvestmentTransactionCost[];
  created_at: string;
  updated_at: string;
}

// =============================================================================
// Request bodies -- exactly the keys the backend accepts
// =============================================================================

/** One Unit as a create or promote request states it. Economic timing is
 * omitted: the backend applies P7.6's only supported timing (closing, through
 * the common hold). */
export interface InvestmentUnitRequest {
  unit_id: string;
  label: string | null;
  unit_kind: UnitKind;
}

/** `POST /investments` and `POST /investments/{id}/promote`. */
export interface InvestmentCreateRequest {
  name: string;
  transaction_price: number;
  units: InvestmentUnitRequest[];
  business_plan: BusinessPlanInput;
  transaction_costs: InvestmentTransactionCost[];
}

/** `PUT /investments/{id}/details`: the four Investment-level inputs, replaced
 * together in one transaction. */
export interface InvestmentDetailsRequest {
  name: string;
  transaction_price: number;
  business_plan: BusinessPlanInput;
  transaction_costs: InvestmentTransactionCost[];
}

/** `POST /investments/{id}/units`. `transaction_price` is the analyst's
 * resulting price, sent in the same request. */
export interface InvestmentAddUnitRequest {
  unit_id: string;
  label: string | null;
  unit_kind: UnitKind;
  transaction_price: number;
}

/** `PUT /investments/{id}/units/{unit_id}`: display metadata only. */
export interface InvestmentUnitDisplayRequest {
  label: string | null;
  unit_kind: UnitKind;
  ordinal: number;
}

// =============================================================================
// Refusals
// =============================================================================

/** One entry of an Investment 422: mirrors `InvestmentIssue` as `api.py`
 * serializes it. `message` is the validator's own wording; `unit_id` names the
 * Unit concerned where there is one. */
export interface InvestmentIssue {
  code: string;
  message: string;
  unit_id: string | null;
  field: string | null;
  source_code: string | null;
}

/** One entry of a visible Investment variant 422: mirrors
 * `InvestmentVariantIssue`. */
export interface InvestmentVariantIssue {
  source: 'strategy' | 'scenario' | 'lease_level' | 'investment';
  code: string;
  message: string;
  unit_id: string | null;
  field: string | null;
}

// =============================================================================
// Consolidated analysis
// =============================================================================

/** Mirrors `AreaMetricReason`. */
export type AreaMetricReason = 'unit_without_area_measure';

/** Mirrors `ConsolidatedResults`, field for field. Annual series are Years 1..H;
 * `unlevered_cash_flows` and `levered_cash_flows` are Years 0..H. */
export interface ConsolidatedResults {
  unit_ids: string[];
  hold_period: number;

  transaction_price: number;
  allocated_purchase_price: number;
  allocation_variance: number;
  acquisition_costs: number;
  financing_fees: number;
  investment_transaction_costs: number;
  investment_closing_project_capital: number;
  closing_project_capital: number;
  loan_amount: number;
  initial_equity: number;
  total_closing_uses: number;
  total_closing_sources: number;
  unlevered_project_basis: number;

  noi_by_year: number[];
  capex_by_year: number[];
  tenant_improvements_by_year: number[];
  leasing_commissions_by_year: number[];
  property_cash_flow_by_year: number[];
  investment_project_capital_by_year: number[];
  investment_owner_expenses_by_year: number[];
  project_capital_by_year: number[];
  owner_expenses_by_year: number[];
  unlevered_owner_cash_flow_by_year: number[];
  annual_debt_service: number[];
  levered_owner_cash_flow_by_year: number[];

  remaining_loan_balance: number;
  exit_noi: number;
  exit_value: number;
  disposition_costs: number;
  net_sale_proceeds: number;
  investment_post_hold_project_capital: number;
  post_hold_project_capital: number;
  implied_exit_cap_rate: number | null;

  unlevered_cash_flows: number[];
  levered_cash_flows: number[];

  unlevered_irr: number | null;
  unlevered_irr_status: IrrStatus;
  levered_irr: number | null;
  levered_irr_status: IrrStatus;
  total_equity_invested: number;
  total_cash_returned: number;
  total_profit: number;
  equity_multiple: number | null;
  net_additional_equity_requirement_by_year: number[];

  aggregate_dscr_by_year: (number | null)[];
  headline_aggregate_dscr: number | null;
  min_aggregate_dscr: number | null;
  going_in_cap_rate: number;
  year_1_debt_yield: number | null;
  levered_cash_on_cash_by_year: (number | null)[];
  unlevered_cash_yield_by_year: (number | null)[];
  cumulative_operating_distributions_by_year: number[];

  physical_occupancy_at_year_end: number[] | null;
  physical_occupancy_reason: AreaMetricReason | null;
  physical_occupancy_message: string | null;
}

/** Mirrors `UnitVariantResult`: one Unit's own complete result envelope,
 * exactly as its mode produces it. */
export interface UnitVariantResult {
  unit_id: string;
  operating_mode: OperatingMode;
  source_fingerprint: string;
  results: AcquisitionResults | DetailedAcquisitionResults | LeaseLevelAcquisitionResults;
}

/** `POST /investments/{id}/investment-variants/{strategy_id}/{scenario_id}/analysis`. */
export interface InvestmentVariantAnalysis {
  investment_id: string;
  strategy_id: string;
  scenario_id: string;
  source_fingerprint: string;
  cache_status: VariantCacheStatus;
  hold_period: number;
  unit_results: UnitVariantResult[];
  consolidated_results: ConsolidatedResults;
}

// =============================================================================
// The Decision Matrix of a visible Investment
// =============================================================================

/** Mirrors `InvestmentMatrixUnit`. */
export interface InvestmentMatrixUnit {
  unit_id: string;
  operating_mode: OperatingMode;
}

/** `POST /investments/{id}/investment-decision-matrix`. The `matrix` is the
 * one P7.5 comparison contract, over consolidated Project metrics. */
export interface InvestmentDecisionMatrixReport {
  investment_id: string;
  units: InvestmentMatrixUnit[];
  matrix: DecisionMatrix;
}
