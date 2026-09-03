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
  /** Underwriting V2 Gate 6 -- the five optional-on-the-backend, but
   * required-once-touched-by-the-analyst, V2 fields. Blank is a distinct,
   * meaningful state (never silently treated as zero) -- see
   * `BLANK_FORM_VALUES`/`buildAcquisitionRequest` in `convert.ts`. */
  acquisitionCostPct: string;
  financingFeePct: string;
  dispositionCostPct: string;
  annualCapexReserve: string;
  ioPeriod: string;
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
  acquisition_cost_pct: number;
  financing_fee_pct: number;
  disposition_cost_pct: number;
  annual_capex_reserve: number;
  io_period: number;
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

/** Underwriting V2 Gate 6: the five optional V2 Field IDs, in canonical
 * order. Mirrors ``V2_FIELD_IDS`` in ``src/anchor/validation.py``. Never
 * extracted by OM ingestion in this gate -- absent from
 * ``ACQUISITION_FIELD_IDS``/``ExtractionResult`` on purpose. */
export const V2_FIELD_IDS = [
  'acquisition_cost_pct',
  'financing_fee_pct',
  'disposition_cost_pct',
  'annual_capex_reserve',
  'io_period',
] as const;

export type V2FieldId = (typeof V2_FIELD_IDS)[number];

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

/** Mirrors ``AcquisitionResults`` in ``src/anchor/engine/contracts.py``,
 * including the Underwriting V2 Gate 2/3/4 fields (``acquisition_costs``,
 * ``financing_fee``, ``capex_by_year``, ``disposition_costs``,
 * ``min_dscr``) and the Owner Return Metrics V3 Gate A2 fields
 * (``levered_cash_on_cash_by_year``, ``unlevered_cash_yield_by_year``,
 * ``cumulative_operating_distributions_by_year``, ``year_1_debt_yield``).
 * Every value here is engine-computed -- the frontend never recalculates
 * any of it. The four Owner Return Metrics fields already exclude sale/
 * refinance proceeds at every year (including the final hold year) and use
 * ``null`` (never ``0``) wherever their denominator is exactly zero -- both
 * are backend-authoritative, never a frontend concern. */
export interface AcquisitionResults {
  going_in_cap_rate: number;
  loan_amount: number;
  acquisition_costs: number;
  financing_fee: number;
  initial_equity: number;
  monthly_debt_service: number;
  annual_debt_service: number[];
  remaining_loan_balance: number;
  noi_by_year: number[];
  capex_by_year: number[];
  exit_noi: number;
  exit_value: number;
  disposition_costs: number;
  net_sale_proceeds: number;
  unlevered_cash_flows: number[];
  levered_cash_flows: number[];
  unlevered_irr: number | null;
  levered_irr: number | null;
  equity_multiple: number | null;
  dscr_by_year: (number | null)[];
  headline_dscr: number | null;
  min_dscr: number | null;
  levered_cash_on_cash_by_year: (number | null)[];
  unlevered_cash_yield_by_year: (number | null)[];
  cumulative_operating_distributions_by_year: number[];
  year_1_debt_yield: number | null;
}

// =============================================================================
// Detailed Operating Model V2.1 Gate 6 -- Detailed Underwrite mode.
//
// Mirrors ``OperatingMode``/``AcquisitionTerms``/``DetailedOperatingInputs``/
// ``DetailedAcquisitionResults`` in ``src/anchor/contracts.py`` and
// ``src/anchor/engine/contracts.py``. Detailed mode never sends or receives
// ``current_noi``/``noi_growth``/``occupancy`` -- those three fields simply
// have no counterpart on any type below, matching the backend engine's
// Gate 3/4 resolution exactly.
// =============================================================================

/** Mirrors ``OperatingMode`` in ``src/anchor/contracts.py``. */
export type OperatingMode = 'quick' | 'detailed';

export interface AcquisitionTermsFormValues {
  purchasePrice: string;
  holdPeriod: string;
  exitCapRate: string;
  ltv: string;
  interestRate: string;
  amortization: string;
  acquisitionCostPct: string;
  financingFeePct: string;
  dispositionCostPct: string;
  annualCapexReserve: string;
  ioPeriod: string;
}

/** Mirrors ``AcquisitionTerms`` in ``src/anchor/contracts.py`` -- the 11
 * acquisition/debt/exit fields shared by both modes. */
export interface AcquisitionTermsRequest {
  purchase_price: number;
  hold_period: number;
  exit_cap_rate: number;
  ltv: number;
  interest_rate: number;
  amortization: number;
  acquisition_cost_pct: number;
  financing_fee_pct: number;
  disposition_cost_pct: number;
  annual_capex_reserve: number;
  io_period: number;
}

export interface DetailedOperatingFormValues {
  grossPotentialRent: string;
  otherIncome: string;
  vacancyCreditLossPct: string;
  propertyTaxes: string;
  insurance: string;
  utilities: string;
  repairsMaintenance: string;
  otherOperatingExpenses: string;
  managementFeePct: string;
  revenueGrowth: string;
  expenseGrowth: string;
}

/** Mirrors ``DetailedOperatingInputs`` in ``src/anchor/contracts.py``. */
export interface DetailedOperatingInputsRequest {
  gross_potential_rent: number;
  other_income: number;
  vacancy_credit_loss_pct: number;
  property_taxes: number;
  insurance: number;
  utilities: number;
  repairs_maintenance: number;
  other_operating_expenses: number;
  management_fee_pct: number;
  revenue_growth: number;
  expense_growth: number;
}

/** The Detailed workspace's combined form state -- the acquisition/debt
 * terms plus the Operating Model section, kept as two nested groups (rather
 * than one flat 22-field object) so each half's own blank/default/conversion
 * helpers can stay as narrow as ``AcquisitionFormValues``'s already are. */
export interface DetailedFormValues {
  terms: AcquisitionTermsFormValues;
  operating: DetailedOperatingFormValues;
}

/** Mirrors ``OperatingProjection`` in ``src/anchor/engine/contracts.py`` --
 * the full Detailed revenue/vacancy/EGI/expense-line/NOI schedule. Every
 * ``_by_year`` field has length ``hold_period`` (Years 1..H); ``exit_noi``
 * is the single Year H+1 scalar. Every value here is engine-computed -- the
 * frontend never recalculates any of it, exactly like ``AcquisitionResults``. */
export interface OperatingProjection {
  gross_potential_rent_by_year: number[];
  other_income_by_year: number[];
  vacancy_credit_loss_by_year: number[];
  effective_gross_income_by_year: number[];
  property_taxes_by_year: number[];
  insurance_by_year: number[];
  utilities_by_year: number[];
  repairs_maintenance_by_year: number[];
  other_operating_expenses_by_year: number[];
  management_fee_by_year: number[];
  total_operating_expenses_by_year: number[];
  noi_by_year: number[];
  exit_noi: number;
  going_in_cap_rate: number;
}

/** Mirrors ``DetailedAcquisitionResults`` in ``src/anchor/engine/contracts.py``
 * -- the response shape ``POST /analyze`` returns for a ``"detailed"``
 * ``operating_mode`` request (Gate 4). ``results`` is the exact same
 * ``AcquisitionResults`` shape a Quick request returns; ``operating_projection``
 * is the additional Detailed-only schedule the institutional operating
 * statement renders from. */
export interface DetailedAcquisitionResults {
  operating_projection: OperatingProjection;
  results: AcquisitionResults;
}

/** Mirrors ``ExcelIntakeReport`` in ``src/anchor/excel_reader.py`` --
 * Underwriting V2 Gate 5's ``POST /ingestion/excel`` response shape.
 * ``defaulted_v2_field_ids`` names exactly which V2 Field IDs were absent
 * from the uploaded workbook and therefore took their neutral backend
 * default -- a compatibility value, not an analyst assumption (Gate 6): the
 * frontend must leave those specific fields blank, never populate them
 * with the backend's 0. */
export interface ExcelIntakeReport {
  inputs: AcquisitionRequest;
  defaulted_v2_field_ids: V2FieldId[];
}

/** Mirrors ``DetailedExcelIntakeReport`` in
 * ``src/anchor/detailed_excel_reader.py`` -- Detailed Operating Model V2.1
 * Gate 10's ``POST /ingestion/excel/detailed`` response shape. Unlike
 * ``ExcelIntakeReport``, there is no defaulted-field concept: every
 * Detailed Field ID is always required, so a successful response always
 * carries all 22 values. Never an ``OperatingProjection`` or
 * ``DetailedAcquisitionResults`` -- Excel ingestion parses proposed
 * assumptions only. */
export interface DetailedExcelIntakeReport {
  terms: AcquisitionTermsRequest;
  detailed_operating_inputs: DetailedOperatingInputsRequest;
  anchor_schema: string;
  schema_version: string;
}

// =============================================================================
// Detailed Operating Model V2.1 Gate 12 -- Detailed OM ingestion.
//
// Mirrors ``ACQUISITION_FIELD_IDS``/``ExtractionResult`` above, over the
// Detailed field set instead. ``DETAILED_TERMS_FIELD_IDS``/
// ``DETAILED_OPERATING_FIELD_IDS`` mirror
// ``anchor.ingestion.contracts.DETAILED_TERMS_FIELD_IDS``/
// ``DETAILED_OPERATING_FIELD_IDS``.
// =============================================================================

export const DETAILED_TERMS_FIELD_IDS = [
  'purchase_price',
  'hold_period',
  'exit_cap_rate',
  'ltv',
  'interest_rate',
  'amortization',
  'acquisition_cost_pct',
  'financing_fee_pct',
  'disposition_cost_pct',
  'annual_capex_reserve',
  'io_period',
] as const;

export type DetailedTermsFieldId = (typeof DETAILED_TERMS_FIELD_IDS)[number];

export const DETAILED_OPERATING_FIELD_IDS = [
  'gross_potential_rent',
  'other_income',
  'vacancy_credit_loss_pct',
  'property_taxes',
  'insurance',
  'utilities',
  'repairs_maintenance',
  'other_operating_expenses',
  'management_fee_pct',
  'revenue_growth',
  'expense_growth',
] as const;

export type DetailedOperatingFieldId = (typeof DETAILED_OPERATING_FIELD_IDS)[number];

/** Mirrors ``DetailedExtractionResult`` in
 * ``src/anchor/ingestion/contracts.py`` -- Gate 12's
 * ``POST /ingestion/om/detailed`` response shape: candidates for the
 * eleven ``AcquisitionTerms`` fields plus the eleven
 * ``DetailedOperatingInputs`` fields a document may support. No
 * ``deal_context`` (out of this gate's target-field scope) and no
 * ``current_noi``/``occupancy``/``noi_growth`` -- there is no field here
 * an analyst could even attempt to approve one into. */
export interface DetailedExtractionResult {
  purchase_price: FieldCandidates;
  hold_period: FieldCandidates;
  exit_cap_rate: FieldCandidates;
  ltv: FieldCandidates;
  interest_rate: FieldCandidates;
  amortization: FieldCandidates;
  acquisition_cost_pct: FieldCandidates;
  financing_fee_pct: FieldCandidates;
  disposition_cost_pct: FieldCandidates;
  annual_capex_reserve: FieldCandidates;
  io_period: FieldCandidates;
  gross_potential_rent: FieldCandidates;
  other_income: FieldCandidates;
  vacancy_credit_loss_pct: FieldCandidates;
  property_taxes: FieldCandidates;
  insurance: FieldCandidates;
  utilities: FieldCandidates;
  repairs_maintenance: FieldCandidates;
  other_operating_expenses: FieldCandidates;
  management_fee_pct: FieldCandidates;
  revenue_growth: FieldCandidates;
  expense_growth: FieldCandidates;
}

/** Mirrors ``Deal`` in ``src/anchor/deals/contracts.py``. A saved deal
 * carries no derived/result data of its own -- reopening it means
 * resubmitting its assumptions to the existing ``/analyze`` endpoint.
 *
 * Detailed Operating Model V2.1 Gate 11: one deal is either ``QUICK``
 * (``inputs`` populated, ``terms``/``detailed_operating_inputs`` both
 * ``null``) or ``DETAILED`` (``terms``/``detailed_operating_inputs``
 * populated, ``inputs`` ``null``) -- never a fabricated
 * ``current_noi``/``noi_growth``/``occupancy`` on a Detailed deal, matching
 * the backend ``Deal`` dataclass's own invariant exactly. */
export interface Deal {
  id: string;
  name: string;
  operating_mode: OperatingMode;
  inputs: AcquisitionRequest | null;
  terms: AcquisitionTermsRequest | null;
  detailed_operating_inputs: DetailedOperatingInputsRequest | null;
  /** Owner Return Metrics V3 Gate A4: optional, user-authored free text
   * describing the investment strategy/business plan -- never an
   * underwriting input, `null` when no context was supplied (including
   * every deal saved before this field existed). */
  deal_context: string | null;
  /** Owner Return Metrics V3 Gate A6: a CACHE of the last successful
   * deterministic analysis for these exact assumptions -- never a new
   * source of truth (Analyze always remains authoritative). `null` when no
   * analysis has been cached yet, or a previously-cached one was
   * invalidated by an assumption change, or the cached artifact could not
   * be read (never surfaced, never blocks opening the deal). The same
   * `AcquisitionResults` shape for a Quick deal (`operating_mode ===
   * 'quick'`); the richer `DetailedAcquisitionResults` envelope
   * (operating projection + results) for a Detailed deal -- mirrors how
   * `inputs` vs. `terms`/`detailed_operating_inputs` already split by mode. */
  analysis_snapshot: AcquisitionResults | DetailedAcquisitionResults | null;
  /** Owner Return Metrics V3 Gate A6: a CACHE of the last successful AI
   * Analyst output for these exact assumptions and this exact
   * `deal_context` -- `null` under the same conditions as
   * `analysis_snapshot` above, plus whenever `deal_context` itself has
   * changed since the AI ran. Identical shape for both modes. */
  ai_snapshot: AIAnalysis | null;
  created_at: string;
  updated_at: string;
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

/** Detailed Operating Model V2.1 Gate 14: mirrors
 * ``StandardDetailedSensitivityPresets`` in
 * ``src/anchor/analysis/contracts.py``. No ``exit_cap_noi_growth`` member --
 * ``noi_growth`` has no ``AcquisitionTerms`` counterpart. */
export interface StandardDetailedSensitivityPresets {
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

/** Detailed Operating Model V2.1 Gate 14: mirrors
 * ``StandardDetailedBreakEvenAnalysis`` in
 * ``src/anchor/analysis/contracts.py``. ``min_noi_growth``/
 * ``min_current_noi`` have no Detailed equivalent -- neither ``noi_growth``
 * nor ``current_noi`` exists on ``AcquisitionTerms``/
 * ``DetailedOperatingInputs``. */
export interface StandardDetailedBreakEvenAnalysis {
  max_purchase_price: BreakEvenResult;
  max_exit_cap_rate: BreakEvenResult;
  max_interest_rate: BreakEvenResult;
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
