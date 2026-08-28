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

/** The 9 existing AcquisitionInputs field ids, in a fixed order. Mirrors
 * ``ACQUISITION_FIELD_IDS`` in ``src/anchor/ingestion/contracts.py``. */
export const ACQUISITION_FIELD_IDS = [
  'purchase_price',
  'current_noi',
  'occupancy',
  'noi_growth',
  'hold_period',
  'exit_cap_rate',
  'ltv',
  'interest_rate',
  'amortization',
] as const;

export type AcquisitionFieldId = (typeof ACQUISITION_FIELD_IDS)[number];

/** Mirrors ``EvidenceStatus`` in ``src/anchor/ingestion/contracts.py``. */
export type EvidenceStatus = 'stated' | 'interpreted' | 'conflicting' | 'unverifiable' | 'missing';

/** Mirrors ``Provenance`` in ``src/anchor/ingestion/contracts.py``. */
export interface Provenance {
  page: number;
  anchor: string;
  snippet: string;
}

/** Mirrors ``ExtractionCandidate`` in ``src/anchor/ingestion/contracts.py``.
 * ``value`` is always a free-form string exactly as GPT proposed it (e.g.
 * "1000000", "5.5%", or "0.055") -- never a pre-parsed number. */
export interface ExtractionCandidate {
  value: string;
  status: EvidenceStatus;
  provenance: Provenance | null;
}

/** Mirrors ``FieldCandidates`` in ``src/anchor/ingestion/contracts.py``.
 * An empty ``candidates`` array means the field is missing (R7); two or
 * more candidates typically carry status "conflicting" (R8). */
export interface FieldCandidates {
  field_id: string;
  candidates: ExtractionCandidate[];
}

/** Mirrors ``DealContext`` in ``src/anchor/ingestion/contracts.py`` --
 * the 5 fixed, read-only deal-context fields (R2/KD5). Never eligible to
 * enter ``AcquisitionRequest``/``AcquisitionInputs``. */
export interface DealContext {
  property_name: FieldCandidates;
  address: FieldCandidates;
  property_type: FieldCandidates;
  unit_count_or_building_area: FieldCandidates;
  year_built: FieldCandidates;
}

/** Mirrors ``ExtractionResult`` in ``src/anchor/ingestion/contracts.py``
 * -- one assembled OM extraction outcome: candidates for the 9
 * ``AcquisitionInputs`` fields plus the 5 read-only deal-context fields. */
export interface ExtractionResult {
  purchase_price: FieldCandidates;
  current_noi: FieldCandidates;
  occupancy: FieldCandidates;
  noi_growth: FieldCandidates;
  hold_period: FieldCandidates;
  exit_cap_rate: FieldCandidates;
  ltv: FieldCandidates;
  interest_rate: FieldCandidates;
  amortization: FieldCandidates;
  deal_context: DealContext;
}

/** Mirrors ``AcquisitionResults`` in ``src/anchor/engine/contracts.py``. */
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

/** Mirrors ``TwoWaySensitivityResult`` in ``src/anchor/analysis/contracts.py``. */
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

/** Mirrors ``StandardSensitivityPresets`` in ``src/anchor/analysis/contracts.py``. */
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
 * Mirrors ``ReturnHurdleMetric`` in ``src/anchor/analysis/contracts.py``. */
export type ReturnHurdleMetric = 'levered_irr' | 'equity_multiple';

/** Mirrors ``BreakEvenResult`` in ``src/anchor/analysis/contracts.py``. */
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

/** Mirrors ``StandardBreakEvenAnalysis`` in ``src/anchor/analysis/contracts.py``. */
export interface StandardBreakEvenAnalysis {
  max_purchase_price: BreakEvenResult;
  max_exit_cap_rate: BreakEvenResult;
  min_noi_growth: BreakEvenResult;
  max_interest_rate: BreakEvenResult;
  min_current_noi: BreakEvenResult;
}

/** Mirrors ``AIAnalysis`` in ``src/anchor/ai/contracts.py`` -- the AI
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
