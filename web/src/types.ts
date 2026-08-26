export interface AcquisitionFormValues {
  purchasePrice: string;
  currentNoi: string;
  occupancy: string;
  noiGrowth: string;
  holdPeriod: string;
  exitCapRate: string;
  ltv: string;
  interestRate: string;
  amortization: string;
}

export interface AcquisitionRequest {
  purchase_price: number;
  current_noi: number;
  occupancy: number;
  noi_growth: number;
  hold_period: number;
  exit_cap_rate: number;
  ltv: number;
  interest_rate: number;
  amortization: number;
}

/** Mirrors ``AcquisitionResults`` in ``src/mini_anchor/engine/contracts.py``. */
export interface AcquisitionResults {
  going_in_cap_rate: number;
  loan_amount: number;
  initial_equity: number;
  monthly_debt_service: number;
  annual_debt_service: number[];
  remaining_loan_balance: number;
  noi_by_year: number[];
  exit_noi: number;
  exit_value: number;
  net_sale_proceeds: number;
  unlevered_cash_flows: number[];
  levered_cash_flows: number[];
  unlevered_irr: number | null;
  levered_irr: number | null;
  equity_multiple: number | null;
  dscr_by_year: (number | null)[];
  headline_dscr: number | null;
}

export interface ValidationIssue {
  field_id: string | null;
  category: string;
  message: string;
}

export type SensitivityMetric = 'levered_irr' | 'headline_dscr';

/** Mirrors ``TwoWaySensitivityResult`` in ``src/mini_anchor/analysis/contracts.py``. */
export interface TwoWaySensitivityResult {
  row_assumption: string;
  column_assumption: string;
  metric: SensitivityMetric;
  baseline_row_value: number;
  baseline_column_value: number;
  baseline_metric_value: number | null;
  row_values: number[];
  column_values: number[];
  matrix: (number | null)[][];
}

/** Mirrors ``StandardSensitivityPresets`` in ``src/mini_anchor/analysis/contracts.py``. */
export interface StandardSensitivityPresets {
  exit_cap_noi_growth: TwoWaySensitivityResult;
  purchase_price_exit_cap: TwoWaySensitivityResult;
  interest_rate_ltv: TwoWaySensitivityResult;
  interest_rate_ltv_dscr: TwoWaySensitivityResult;
}

export type BreakEvenType =
  | 'max_purchase_price'
  | 'max_exit_cap_rate'
  | 'min_noi_growth'
  | 'max_interest_rate'
  | 'min_current_noi';

export type BreakEvenStatus = 'solved' | 'no_solution_in_range';

export type BreakEvenMetric = 'levered_irr' | 'headline_dscr' | 'equity_multiple';

/** Which return metric drives the three return-hurdle break-even questions
 * (Maximum Purchase Price, Maximum Exit Cap Rate, Minimum NOI Growth).
 * Mirrors ``ReturnHurdleMetric`` in ``src/mini_anchor/analysis/contracts.py``. */
export type ReturnHurdleMetric = 'levered_irr' | 'equity_multiple';

/** Mirrors ``BreakEvenResult`` in ``src/mini_anchor/analysis/contracts.py``. */
export interface BreakEvenResult {
  break_even_type: BreakEvenType;
  assumption: string;
  metric: BreakEvenMetric;
  target_metric_value: number;
  baseline_assumption_value: number;
  baseline_metric_value: number | null;
  solved_assumption_value: number | null;
  solved_metric_value: number | null;
  lower_search_bound: number;
  upper_search_bound: number;
  status: BreakEvenStatus;
}

/** Mirrors ``StandardBreakEvenAnalysis`` in ``src/mini_anchor/analysis/contracts.py``. */
export interface StandardBreakEvenAnalysis {
  max_purchase_price: BreakEvenResult;
  max_exit_cap_rate: BreakEvenResult;
  min_noi_growth: BreakEvenResult;
  max_interest_rate: BreakEvenResult;
  min_current_noi: BreakEvenResult;
}

/** Mirrors ``AIAnalysis`` in ``src/mini_anchor/ai/contracts.py`` -- the AI
 * Analyst's structured, interpretation-only output. Never carries a newly
 * calculated financial metric. */
export interface AIAnalysis {
  executive_summary: string;
  investment_view: string;
  strengths: string[];
  risks: string[];
  return_drivers: string[];
  downside_analysis: string;
  capital_structure_analysis: string;
  break_even_analysis: string;
  questions_to_investigate: string[];
  confidence_notes: string[];
}
