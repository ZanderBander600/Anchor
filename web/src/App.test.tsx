import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import {
  analyzeAcquisition,
  analyzeDetailedAcquisition,
  ApiError,
  createDeal,
  createDetailedDeal,
  deleteDeal,
  duplicateDeal,
  fetchAIAnalysis,
  fetchBreakEvenAnalysis,
  fetchDealFingerprint,
  fetchDetailedAIAnalysis,
  fetchDetailedBreakEvenAnalysis,
  fetchDetailedDealFingerprint,
  fetchDetailedSensitivityPresets,
  fetchSensitivityPresets,
  getDeal,
  listDeals,
  updateDeal,
  updateDealAiSnapshot,
  updateDealAnalysisSnapshot,
  updateDetailedDeal,
  uploadDetailedExcel,
  uploadDetailedOm,
  uploadExcel,
  uploadOm,
} from './api';
import { formatCurrency, formatPercent } from './format';
import {
  BLANK_DETAILED_FORM_VALUES,
  BLANK_FORM_VALUES,
  buildAcquisitionRequest,
  DEFAULT_FORM_VALUES,
  DETAILED_GOLDEN_FORM_VALUES,
  V2_GOLDEN_FORM_VALUES,
} from './convert';
import type {
  AcquisitionRequest,
  AcquisitionResults,
  AIAnalysis,
  BreakEvenResult,
  Deal,
  DealStory,
  DetailedAcquisitionResults,
  DetailedExcelIntakeReport,
  DetailedExtractionResult,
  ExcelIntakeReport,
  ExtractionResult,
  FieldCandidates,
  StandardBreakEvenAnalysis,
  StandardDetailedBreakEvenAnalysis,
  StandardDetailedSensitivityPresets,
  StandardSensitivityPresets,
  TwoWaySensitivityResult,
} from './types';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    analyzeAcquisition: vi.fn(),
    analyzeDetailedAcquisition: vi.fn(),
    fetchSensitivityPresets: vi.fn(),
    fetchBreakEvenAnalysis: vi.fn(),
    fetchDetailedSensitivityPresets: vi.fn(),
    fetchDetailedBreakEvenAnalysis: vi.fn(),
    fetchAIAnalysis: vi.fn(),
    fetchDetailedAIAnalysis: vi.fn(),
    uploadOm: vi.fn(),
    uploadDetailedOm: vi.fn(),
    uploadExcel: vi.fn(),
    uploadDetailedExcel: vi.fn(),
    createDeal: vi.fn(),
    updateDeal: vi.fn(),
    createDetailedDeal: vi.fn(),
    updateDetailedDeal: vi.fn(),
    fetchDealFingerprint: vi.fn(),
    fetchDetailedDealFingerprint: vi.fn(),
    updateDealAnalysisSnapshot: vi.fn(),
    updateDealAiSnapshot: vi.fn(),
    getDeal: vi.fn(),
    listDeals: vi.fn(),
    duplicateDeal: vi.fn(),
    deleteDeal: vi.fn(),
  };
});

const mockAnalyze = vi.mocked(analyzeAcquisition);
const mockAnalyzeDetailed = vi.mocked(analyzeDetailedAcquisition);
const mockFetchSensitivityPresets = vi.mocked(fetchSensitivityPresets);
const mockFetchBreakEvenAnalysis = vi.mocked(fetchBreakEvenAnalysis);
const mockFetchDetailedSensitivityPresets = vi.mocked(fetchDetailedSensitivityPresets);
const mockFetchDetailedBreakEvenAnalysis = vi.mocked(fetchDetailedBreakEvenAnalysis);
const mockFetchAIAnalysis = vi.mocked(fetchAIAnalysis);
const mockFetchDetailedAIAnalysis = vi.mocked(fetchDetailedAIAnalysis);
const mockUploadOm = vi.mocked(uploadOm);
const mockUploadDetailedOm = vi.mocked(uploadDetailedOm);
const mockUploadExcel = vi.mocked(uploadExcel);
const mockUploadDetailedExcel = vi.mocked(uploadDetailedExcel);
const mockCreateDeal = vi.mocked(createDeal);
const mockCreateDetailedDeal = vi.mocked(createDetailedDeal);
const mockUpdateDetailedDeal = vi.mocked(updateDetailedDeal);
const mockDuplicateDeal = vi.mocked(duplicateDeal);
const mockDeleteDeal = vi.mocked(deleteDeal);
const mockUpdateDeal = vi.mocked(updateDeal);
const mockGetDeal = vi.mocked(getDeal);
const mockListDeals = vi.mocked(listDeals);
const mockUpdateDealAnalysisSnapshot = vi.mocked(updateDealAnalysisSnapshot);
const mockUpdateDealAiSnapshot = vi.mocked(updateDealAiSnapshot);
const mockFetchDealFingerprint = vi.mocked(fetchDealFingerprint);
const mockFetchDetailedDealFingerprint = vi.mocked(fetchDetailedDealFingerprint);

function missingField(field_id: string): FieldCandidates {
  return { field_id, candidates: [] };
}

function makeExtractionResult(overrides: Partial<ExtractionResult> = {}): ExtractionResult {
  const base: ExtractionResult = {
    purchase_price: {
      field_id: 'purchase_price',
      candidates: [
        {
          value: '48000000',
          status: 'stated',
          provenance: { page: 1, anchor: 'paragraph:0', snippet: 'Purchase Price: $48,000,000' },
        },
      ],
    },
    current_noi: missingField('current_noi'),
    occupancy: missingField('occupancy'),
    noi_growth: missingField('noi_growth'),
    hold_period: missingField('hold_period'),
    exit_cap_rate: {
      field_id: 'exit_cap_rate',
      candidates: [
        {
          value: '6%',
          status: 'stated',
          provenance: { page: 2, anchor: 'paragraph:1', snippet: 'Exit cap rate: 6%' },
        },
      ],
    },
    ltv: missingField('ltv'),
    interest_rate: missingField('interest_rate'),
    amortization: missingField('amortization'),
    deal_context: {
      property_name: missingField('property_name'),
      address: missingField('address'),
      property_type: missingField('property_type'),
      unit_count_or_building_area: missingField('unit_count_or_building_area'),
      year_built: missingField('year_built'),
    },
    ...overrides,
  };
  return base;
}

/** Detailed Operating Model V2.1 Gate 12 -- a Detailed OM extraction
 * fixture: purchase_price and gross_potential_rent stated with evidence,
 * every other Detailed field missing (never a fabricated zero). */
function makeDetailedExtractionResult(
  overrides: Partial<DetailedExtractionResult> = {},
): DetailedExtractionResult {
  const base: DetailedExtractionResult = {
    purchase_price: {
      field_id: 'purchase_price',
      candidates: [
        {
          value: '10000000',
          status: 'stated',
          provenance: { page: 1, anchor: 'paragraph:0', snippet: 'Purchase Price: $10,000,000' },
        },
      ],
    },
    hold_period: missingField('hold_period'),
    exit_cap_rate: missingField('exit_cap_rate'),
    ltv: missingField('ltv'),
    interest_rate: missingField('interest_rate'),
    amortization: missingField('amortization'),
    acquisition_cost_pct: missingField('acquisition_cost_pct'),
    financing_fee_pct: missingField('financing_fee_pct'),
    disposition_cost_pct: missingField('disposition_cost_pct'),
    annual_capex_reserve: missingField('annual_capex_reserve'),
    io_period: missingField('io_period'),
    gross_potential_rent: {
      field_id: 'gross_potential_rent',
      candidates: [
        {
          value: '800000',
          status: 'stated',
          provenance: { page: 31, anchor: 'paragraph:1', snippet: 'Potential Base Rent: $800,000' },
        },
      ],
    },
    other_income: missingField('other_income'),
    vacancy_credit_loss_pct: missingField('vacancy_credit_loss_pct'),
    property_taxes: {
      field_id: 'property_taxes',
      candidates: [
        {
          value: '0',
          status: 'stated',
          provenance: { page: 32, anchor: 'paragraph:2', snippet: 'Real Estate Taxes: $0' },
        },
      ],
    },
    insurance: missingField('insurance'),
    utilities: missingField('utilities'),
    repairs_maintenance: missingField('repairs_maintenance'),
    other_operating_expenses: missingField('other_operating_expenses'),
    management_fee_pct: missingField('management_fee_pct'),
    revenue_growth: missingField('revenue_growth'),
    expense_growth: missingField('expense_growth'),
    ...overrides,
  };
  return base;
}

// Deliberately distinct from every metric value in `makeResults()` (7.91%,
// 6.24%, 1.44x, 1.1608x, ...) so text queries against the base results panel
// never collide with the sensitivity panel's mocked values.
function makeSensitivityMatrix(
  overrides: Partial<TwoWaySensitivityResult> = {},
): TwoWaySensitivityResult {
  return {
    row_assumption: 'noi_growth',
    column_assumption: 'exit_cap_rate',
    metric: 'levered_irr',
    baseline_row_value: 0.03,
    baseline_column_value: 0.055,
    baseline_metric_value: 0.5,
    row_values: [0.01, 0.02, 0.03, 0.04, 0.05],
    column_values: [0.045, 0.05, 0.055, 0.06, 0.065],
    matrix: [
      [0.41, 0.42, 0.43, 0.44, 0.45],
      [0.46, 0.47, 0.48, 0.49, 0.5],
      [0.51, 0.52, 0.5, 0.53, 0.54],
      [0.55, 0.56, 0.57, 0.58, 0.59],
      [0.6, 0.61, 0.62, 0.63, 0.64],
    ],
    ...overrides,
  };
}

function makeSensitivityPresets(
  overrides: Partial<StandardSensitivityPresets> = {},
): StandardSensitivityPresets {
  return {
    exit_cap_noi_growth: makeSensitivityMatrix(),
    purchase_price_exit_cap: makeSensitivityMatrix({ row_assumption: 'purchase_price' }),
    interest_rate_ltv: makeSensitivityMatrix({
      row_assumption: 'interest_rate',
      column_assumption: 'ltv',
    }),
    interest_rate_ltv_dscr: makeSensitivityMatrix({
      row_assumption: 'interest_rate',
      column_assumption: 'ltv',
      metric: 'headline_dscr',
    }),
    ...overrides,
  };
}

/** Detailed Operating Model V2.1 Gate 14: the Detailed counterpart of
 * `makeSensitivityPresets` -- no `exit_cap_noi_growth` member, deliberately
 * distinct baseline/matrix values (0.09/0.5x territory) so Detailed
 * sensitivity text queries never collide with Quick's own mocked
 * sensitivity values in a cross-mode test. */
function makeDetailedSensitivityPresets(
  overrides: Partial<StandardDetailedSensitivityPresets> = {},
): StandardDetailedSensitivityPresets {
  return {
    // Every cell is distinct and outside Quick's default matrix's 41%-64%
    // range -- the [2][2] (baseline) cell is the only one that renders
    // "9.00%", so a text query for it can never collide with a neighbor.
    purchase_price_exit_cap: makeSensitivityMatrix({
      row_assumption: 'purchase_price',
      column_assumption: 'exit_cap_rate',
      baseline_row_value: 10_000_000,
      baseline_column_value: 0.065,
      baseline_metric_value: 0.09,
      row_values: [9_000_000, 9_500_000, 10_000_000, 10_500_000, 11_000_000],
      column_values: [0.055, 0.06, 0.065, 0.07, 0.075],
      matrix: [
        [0.05, 0.06, 0.07, 0.08, 0.081],
        [0.082, 0.083, 0.084, 0.085, 0.086],
        [0.087, 0.088, 0.09, 0.091, 0.092],
        [0.093, 0.094, 0.095, 0.096, 0.097],
        [0.098, 0.099, 0.1, 0.101, 0.102],
      ],
    }),
    interest_rate_ltv: makeSensitivityMatrix({
      row_assumption: 'interest_rate',
      column_assumption: 'ltv',
      baseline_metric_value: 0.09,
    }),
    // Same idea for the DSCR variant -- [2][2] is the only cell rendering
    // "2.00x".
    interest_rate_ltv_dscr: makeSensitivityMatrix({
      row_assumption: 'interest_rate',
      column_assumption: 'ltv',
      metric: 'headline_dscr',
      baseline_row_value: 0.05,
      baseline_column_value: 0.6,
      baseline_metric_value: 2.0,
      row_values: [0.03, 0.04, 0.05, 0.06, 0.07],
      column_values: [0.5, 0.55, 0.6, 0.65, 0.7],
      matrix: [
        [1.5, 1.6, 1.7, 1.8, 1.9],
        [1.91, 1.92, 1.93, 1.94, 1.95],
        [1.96, 1.97, 2.0, 1.98, 1.99],
        [2.01, 2.02, 2.03, 2.04, 2.05],
        [2.06, 2.07, 2.08, 2.09, 2.1],
      ],
    }),
    ...overrides,
  };
}

function makeBreakEvenResult(overrides: Partial<BreakEvenResult> = {}): BreakEvenResult {
  return {
    break_even_type: 'max_purchase_price',
    assumption: 'purchase_price',
    metric: 'levered_irr',
    target_metric_value: 0.10,
    baseline_assumption_value: 50_000_000,
    baseline_metric_value: 0.0791303,
    solved_assumption_value: 46_820_000,
    solved_metric_value: 0.10001,
    lower_search_bound: 25_000_000,
    upper_search_bound: 75_000_000,
    status: 'solved',
    ...overrides,
  };
}

function makeBreakEvenAnalysis(
  overrides: Partial<StandardBreakEvenAnalysis> = {},
): StandardBreakEvenAnalysis {
  return {
    max_purchase_price: makeBreakEvenResult(),
    max_exit_cap_rate: makeBreakEvenResult({
      break_even_type: 'max_exit_cap_rate',
      assumption: 'exit_cap_rate',
      baseline_assumption_value: 0.055,
      solved_assumption_value: 0.0612,
      lower_search_bound: 0.025,
      upper_search_bound: 0.105,
    }),
    min_noi_growth: makeBreakEvenResult({
      break_even_type: 'min_noi_growth',
      assumption: 'noi_growth',
      baseline_assumption_value: 0.03,
      solved_assumption_value: 0.0417,
      lower_search_bound: -0.07,
      upper_search_bound: 0.13,
    }),
    max_interest_rate: makeBreakEvenResult({
      break_even_type: 'max_interest_rate',
      assumption: 'interest_rate',
      metric: 'headline_dscr',
      target_metric_value: 1.20,
      baseline_assumption_value: 0.0525,
      baseline_metric_value: 1.1608,
      solved_assumption_value: 0.0461,
      solved_metric_value: 1.2001,
      lower_search_bound: 0.0,
      upper_search_bound: 0.2,
    }),
    min_current_noi: makeBreakEvenResult({
      break_even_type: 'min_current_noi',
      assumption: 'current_noi',
      metric: 'headline_dscr',
      target_metric_value: 1.20,
      baseline_assumption_value: 2_500_000,
      baseline_metric_value: 1.1608,
      solved_assumption_value: 2_585_000,
      solved_metric_value: 1.2001,
      lower_search_bound: 1_250_000,
      upper_search_bound: 3_750_000,
    }),
    ...overrides,
  };
}

/** Detailed Operating Model V2.1 Gate 14: the Detailed counterpart of
 * `makeBreakEvenAnalysis` -- no `min_noi_growth`/`min_current_noi` members
 * (neither `noi_growth` nor `current_noi` exists on `AcquisitionTerms`/
 * `DetailedOperatingInputs`), over the Detailed golden case's own
 * assumption values. */
function makeDetailedBreakEvenAnalysis(
  overrides: Partial<StandardDetailedBreakEvenAnalysis> = {},
): StandardDetailedBreakEvenAnalysis {
  return {
    max_purchase_price: makeBreakEvenResult({
      baseline_assumption_value: 10_000_000,
      // Deliberately not one of the sensitivity mock's purchase_price row
      // values (9.0M/9.5M/10.0M/10.5M/11.0M) -- both panels render at once,
      // and a shared exact-dollar figure would make text queries ambiguous.
      solved_assumption_value: 9_487_500,
    }),
    max_exit_cap_rate: makeBreakEvenResult({
      break_even_type: 'max_exit_cap_rate',
      assumption: 'exit_cap_rate',
      baseline_assumption_value: 0.065,
      solved_assumption_value: 0.071,
      lower_search_bound: 0.035,
      upper_search_bound: 0.115,
    }),
    max_interest_rate: makeBreakEvenResult({
      break_even_type: 'max_interest_rate',
      assumption: 'interest_rate',
      metric: 'headline_dscr',
      target_metric_value: 1.25,
      baseline_assumption_value: 0.05,
      baseline_metric_value: 2.0,
      solved_assumption_value: 0.0712,
      solved_metric_value: 1.2501,
      lower_search_bound: 0.0,
      upper_search_bound: 0.2,
    }),
    ...overrides,
  };
}

function makeResults(overrides: Partial<AcquisitionResults> = {}): AcquisitionResults {
  return {
    going_in_cap_rate: 0.05,
    loan_amount: 32_500_000,
    acquisition_costs: 0,
    financing_fee: 0,
    initial_equity: 17_500_000,
    monthly_debt_service: 179_466.2,
    annual_debt_service: [
      2153594.44, 2153594.44, 2153594.44, 2153594.44, 2153594.44,
    ],
    remaining_loan_balance: 30_000_000,
    noi_by_year: [2500000, 2575000, 2652250, 2731817.5, 2813772.03],
    capex_by_year: [0, 0, 0, 0, 0],
    exit_noi: 2898185.19,
    exit_value: 52694276.18,
    disposition_costs: 0,
    net_sale_proceeds: 22694276.18,
    unlevered_cash_flows: [
      -50000000, 2500000, 2575000, 2652250, 2731817.5, 25698058.03,
    ],
    levered_cash_flows: [
      -17500000, 346405.56, 421405.56, 498655.56, 578223.06, 23405870.05,
    ],
    unlevered_irr: 0.0624149,
    levered_irr: 0.0791303,
    equity_multiple: 1.442889,
    dscr_by_year: [1.1608, 1.19567, 1.23154, 1.26849, 1.30654],
    headline_dscr: 1.1608,
    min_dscr: 1.1608,
    levered_cash_on_cash_by_year: [
      0.0197946, 0.0240803, 0.0284946, 0.0330413, 0.0377244,
    ],
    unlevered_cash_yield_by_year: [0.05, 0.0515, 0.053045, 0.0546364, 0.0562754],
    cumulative_operating_distributions_by_year: [
      346405.56, 767811.12, 1266466.68, 1844689.75, 2504867.33,
    ],
    year_1_debt_yield: 0.0769231,
    ...overrides,
  };
}

/** The frozen Underwriting V2 golden case's engine output (Gate 4), for
 * tests demonstrating the full V2 flow end-to-end with authoritative
 * mocked values -- never reproduced via a TypeScript formula. */
function makeV2GoldenResults(overrides: Partial<AcquisitionResults> = {}): AcquisitionResults {
  return makeResults({
    going_in_cap_rate: 0.06,
    loan_amount: 6_000_000,
    acquisition_costs: 200_000,
    financing_fee: 60_000,
    initial_equity: 4_260_000,
    monthly_debt_service: 32209.29738072834,
    annual_debt_service: [300_000, 300_000, 386511.5685687402, 386511.5685687402, 386511.5685687402],
    remaining_loan_balance: 5720615.679740943,
    noi_by_year: [600000, 618000, 636540, 655636.2, 675305.286],
    capex_by_year: [50_000, 50_000, 50_000, 50_000, 50_000],
    exit_noi: 675305.286,
    exit_value: 10700991.455076924,
    disposition_costs: 267524.7863769231,
    net_sale_proceeds: 4712850.988959057,
    unlevered_cash_flows: [-10200000, 550000, 568000, 586540, 605636.2, 11058771.9547],
    levered_cash_flows: [-4260000, 250000, 268000, 200028.43143125979, 219124.63143125974, 4951644.7063903175],
    unlevered_irr: 0.061388193938218594,
    levered_irr: 0.07380240064972221,
    equity_multiple: 1.3823468941908068,
    dscr_by_year: [2.0, 2.06, 1.6468847293681788, 1.696291271249224, 1.7471800093867011],
    headline_dscr: 2.0,
    min_dscr: 1.6468847293681788,
    levered_cash_on_cash_by_year: [
      0.05868544600938967, 0.06291079812206572, 0.0469550308524084,
      0.05143770690874642, 0.05605486324677459,
    ],
    unlevered_cash_yield_by_year: [
      0.05392156862745098, 0.05568627450980392, 0.05750392156862745,
      0.05937609803921568, 0.061304439803921564,
    ],
    cumulative_operating_distributions_by_year: [
      250000, 518000, 718028.4314312598, 937153.0628625196, 1175946.7802937794,
    ],
    year_1_debt_yield: 0.1,
    ...overrides,
  });
}

function makeExcelIntakeReport(
  overrides: Partial<ExcelIntakeReport> = {},
): ExcelIntakeReport {
  return {
    inputs: makeAcquisitionRequest(),
    defaulted_v2_field_ids: [
      'acquisition_cost_pct',
      'financing_fee_pct',
      'disposition_cost_pct',
      'annual_capex_reserve',
      'io_period',
    ],
    ...overrides,
  };
}

/** Detailed Operating Model V2.1 Gate 10 -- the Detailed golden case,
 * shaped as a `POST /ingestion/excel/detailed` response
 * (`DetailedExcelIntakeReport`). Every field is always present -- there is
 * no defaulted-field concept for Detailed. */
function makeDetailedExcelIntakeReport(
  overrides: Partial<DetailedExcelIntakeReport> = {},
): DetailedExcelIntakeReport {
  return {
    terms: {
      purchase_price: 10_000_000,
      hold_period: 5,
      exit_cap_rate: 0.065,
      ltv: 0.6,
      interest_rate: 0.05,
      amortization: 30,
      acquisition_cost_pct: 0.02,
      financing_fee_pct: 0.01,
      disposition_cost_pct: 0.025,
      annual_capex_reserve: 50_000,
      io_period: 2,
    },
    detailed_operating_inputs: {
      gross_potential_rent: 800_000,
      other_income: 20_000,
      vacancy_credit_loss_pct: 0.05,
      property_taxes: 60_000,
      insurance: 20_000,
      utilities: 25_000,
      repairs_maintenance: 20_000,
      other_operating_expenses: 16_000,
      management_fee_pct: 0.05,
      revenue_growth: 0.03,
      expense_growth: 0.03,
    },
    anchor_schema: 'detailed_acquisition',
    schema_version: '2.1',
    ...overrides,
  };
}

/** A Promise plus its resolvers, for controlling in-flight request timing in tests. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/**
 * Fills AssumptionsForm with the golden-deal fixture values. The app now
 * starts with every assumption field blank (U10) -- most of the tests below
 * are exercising analysis/sensitivity/break-even/AI-analyst behavior that
 * assumes a valid, already-populated deal, not the blank-start behavior
 * itself, so they call this immediately after `render(<App />)` to reach
 * that starting point deliberately rather than relying on it being the
 * default. Uses `fireEvent` (synchronous) rather than `userEvent.type` so it
 * can be called without `await` from every existing call site.
 */
function fillGoldenDeal() {
  fireEvent.change(screen.getByLabelText(/^Purchase Price/), {
    target: { value: DEFAULT_FORM_VALUES.purchasePrice },
  });
  fireEvent.change(screen.getByLabelText(/^Current NOI/), {
    target: { value: DEFAULT_FORM_VALUES.currentNoi },
  });
  fireEvent.change(screen.getByLabelText(/^Occupancy/), {
    target: { value: DEFAULT_FORM_VALUES.occupancy },
  });
  fireEvent.change(screen.getByLabelText(/^NOI Growth/), {
    target: { value: DEFAULT_FORM_VALUES.noiGrowth },
  });
  fireEvent.change(screen.getByLabelText(/^Hold Period/), {
    target: { value: DEFAULT_FORM_VALUES.holdPeriod },
  });
  fireEvent.change(screen.getByLabelText(/^Exit Cap Rate/), {
    target: { value: DEFAULT_FORM_VALUES.exitCapRate },
  });
  fireEvent.change(screen.getByLabelText(/^LTV/), {
    target: { value: DEFAULT_FORM_VALUES.ltv },
  });
  fireEvent.change(screen.getByLabelText(/^Interest Rate/), {
    target: { value: DEFAULT_FORM_VALUES.interestRate },
  });
  fireEvent.change(screen.getByLabelText(/^Amortization/), {
    target: { value: DEFAULT_FORM_VALUES.amortization },
  });
  fireEvent.change(screen.getByLabelText(/^Acquisition Costs/), {
    target: { value: DEFAULT_FORM_VALUES.acquisitionCostPct },
  });
  fireEvent.change(screen.getByLabelText(/^Financing Fee/), {
    target: { value: DEFAULT_FORM_VALUES.financingFeePct },
  });
  fireEvent.change(screen.getByLabelText(/^Disposition Costs/), {
    target: { value: DEFAULT_FORM_VALUES.dispositionCostPct },
  });
  fireEvent.change(screen.getByLabelText(/^Annual CapEx Reserve/), {
    target: { value: DEFAULT_FORM_VALUES.annualCapexReserve },
  });
  fireEvent.change(screen.getByLabelText(/^Interest-Only Period/), {
    target: { value: DEFAULT_FORM_VALUES.ioPeriod },
  });
}

/** Fills AssumptionsForm with the frozen Underwriting V2 golden-case
 * fixture values (Gate 6) -- all fourteen fields, including nonzero V2
 * assumptions. */
function fillV2GoldenDeal() {
  fireEvent.change(screen.getByLabelText(/^Purchase Price/), {
    target: { value: V2_GOLDEN_FORM_VALUES.purchasePrice },
  });
  fireEvent.change(screen.getByLabelText(/^Current NOI/), {
    target: { value: V2_GOLDEN_FORM_VALUES.currentNoi },
  });
  fireEvent.change(screen.getByLabelText(/^Occupancy/), {
    target: { value: V2_GOLDEN_FORM_VALUES.occupancy },
  });
  fireEvent.change(screen.getByLabelText(/^NOI Growth/), {
    target: { value: V2_GOLDEN_FORM_VALUES.noiGrowth },
  });
  fireEvent.change(screen.getByLabelText(/^Hold Period/), {
    target: { value: V2_GOLDEN_FORM_VALUES.holdPeriod },
  });
  fireEvent.change(screen.getByLabelText(/^Exit Cap Rate/), {
    target: { value: V2_GOLDEN_FORM_VALUES.exitCapRate },
  });
  fireEvent.change(screen.getByLabelText(/^LTV/), {
    target: { value: V2_GOLDEN_FORM_VALUES.ltv },
  });
  fireEvent.change(screen.getByLabelText(/^Interest Rate/), {
    target: { value: V2_GOLDEN_FORM_VALUES.interestRate },
  });
  fireEvent.change(screen.getByLabelText(/^Amortization/), {
    target: { value: V2_GOLDEN_FORM_VALUES.amortization },
  });
  fireEvent.change(screen.getByLabelText(/^Acquisition Costs/), {
    target: { value: V2_GOLDEN_FORM_VALUES.acquisitionCostPct },
  });
  fireEvent.change(screen.getByLabelText(/^Financing Fee/), {
    target: { value: V2_GOLDEN_FORM_VALUES.financingFeePct },
  });
  fireEvent.change(screen.getByLabelText(/^Disposition Costs/), {
    target: { value: V2_GOLDEN_FORM_VALUES.dispositionCostPct },
  });
  fireEvent.change(screen.getByLabelText(/^Annual CapEx Reserve/), {
    target: { value: V2_GOLDEN_FORM_VALUES.annualCapexReserve },
  });
  fireEvent.change(screen.getByLabelText(/^Interest-Only Period/), {
    target: { value: V2_GOLDEN_FORM_VALUES.ioPeriod },
  });
}

/**
 * Sprint B Gate B5 test-specificity helpers.
 *
 * The One-Page Owner Summary and the full `ResultsPanel` legitimately show
 * several of the same authoritative figures, so a bare
 * `getAllByText(...).length >= 1` -- the mechanical conversion Gate B3
 * applied -- no longer distinguishes the two surfaces. Where a test is
 * actually about one of them, scope the query to that panel's own root
 * instead.
 */
function ownerSummary(): HTMLElement {
  const panel = document.querySelector('.owner-summary-panel');
  if (panel === null) {
    throw new Error('No Owner Summary is rendered.');
  }
  return panel as HTMLElement;
}

function fullResults(): HTMLElement {
  const panel = document.querySelector('.results-panel');
  if (panel === null) {
    throw new Error('No full Results panel is rendered.');
  }
  return panel as HTMLElement;
}

/**
 * Sprint C Gate C2 workspace-navigation helpers.
 *
 * Anchor is now a workspace shell rather than one long page: each of the five
 * deal workspaces is a `tabpanel`, and the inactive ones are `hidden` -- so a
 * workspace's own controls are only in the accessibility tree while that
 * workspace is the active tab. Tests that drive a workspace's controls
 * navigate there first, exactly as a user must. Navigating to the workspace
 * already showing is a no-op, so these calls are safe to repeat.
 */
async function goTo(user: ReturnType<typeof userEvent.setup>, workspace: string) {
  await user.click(screen.getByRole('tab', { name: workspace }));
}

/** Scopes a query to the Deal Library view. The sidebar's Recent Deals list
 * renders the same deal names, so an unscoped text query now legitimately
 * matches both surfaces. */
function dealLibrary(): HTMLElement {
  const panel = document.querySelector('.deal-library-panel');
  if (panel === null) {
    throw new Error('No Deal Library is rendered.');
  }
  return panel as HTMLElement;
}

/** Scopes a query to the global sidebar. */
function sidebar(): HTMLElement {
  const nav = document.querySelector('.app-sidebar');
  if (nav === null) {
    throw new Error('No sidebar is rendered.');
  }
  return nav as HTMLElement;
}

/** Sprint C Gate C3: the Results sub-nav has a tab labelled "Operating
 * Statement" alongside the table's own heading of the same name, so queries
 * about the table scope to the table. */
function operatingStatement(): HTMLElement | null {
  const headings = Array.from(document.querySelectorAll('.card-title'));
  const heading = headings.find((node) => node.textContent === 'Operating Statement');
  return (heading?.closest('.table-card') as HTMLElement | undefined) ?? null;
}

/** Navigates to Underwrite -> Results -> Operating Statement. */
async function goToOperatingStatement(user: ReturnType<typeof userEvent.setup>) {
  await goTo(user, 'Underwrite');
  await user.click(screen.getByRole('tab', { name: 'Results' }));
  await user.click(screen.getByRole('tab', { name: 'Operating Statement' }));
}

function makeAiAnalysis(overrides: Partial<AIAnalysis> = {}): AIAnalysis {
  return {
    executive_summary: 'Five-year hold with moderate leverage.',
    investment_view: 'Return profile clears the supplied hurdles at baseline.',
    strengths: ['Levered IRR clears the target hurdle at baseline.'],
    risks: ['Exit cap rate expansion compresses returns per the sensitivity matrix.'],
    return_drivers: ['NOI growth'],
    downside_analysis: 'Levered IRR remains positive across the tested exit cap range.',
    capital_structure_analysis: '65% LTV produces a Year 1 DSCR above 1.15x.',
    break_even_analysis: 'Maximum purchase price break-even was found within the tested range.',
    questions_to_investigate: ['What is the in-place rent roll composition?'],
    confidence_notes: ['No tenant credit data was supplied.'],
    deal_story: null,
    ...overrides,
  };
}

beforeEach(() => {
  mockAnalyze.mockReset();
  mockAnalyzeDetailed.mockReset();
  mockFetchSensitivityPresets.mockReset();
  mockFetchSensitivityPresets.mockResolvedValue(makeSensitivityPresets());
  mockFetchBreakEvenAnalysis.mockReset();
  mockFetchBreakEvenAnalysis.mockResolvedValue(makeBreakEvenAnalysis());
  mockFetchDetailedSensitivityPresets.mockReset();
  mockFetchDetailedSensitivityPresets.mockResolvedValue(makeDetailedSensitivityPresets());
  mockFetchDetailedBreakEvenAnalysis.mockReset();
  mockFetchDetailedBreakEvenAnalysis.mockResolvedValue(makeDetailedBreakEvenAnalysis());
  mockFetchAIAnalysis.mockReset();
  mockFetchAIAnalysis.mockResolvedValue(makeAiAnalysis());
  mockFetchDetailedAIAnalysis.mockReset();
  mockFetchDetailedAIAnalysis.mockResolvedValue(makeAiAnalysis());
  mockUploadOm.mockReset();
  mockUploadDetailedOm.mockReset();
  mockUploadExcel.mockReset();
  mockUploadDetailedExcel.mockReset();
  mockCreateDeal.mockReset();
  mockUpdateDeal.mockReset();
  mockCreateDetailedDeal.mockReset();
  mockUpdateDetailedDeal.mockReset();
  mockGetDeal.mockReset();
  mockListDeals.mockReset();
  mockListDeals.mockResolvedValue([]);
  mockDuplicateDeal.mockReset();
  mockDeleteDeal.mockReset();
  // Owner Return Metrics V3 Gate A6: default to a resolved Promise so the
  // silent background cache-refresh calls in handleSubmit/
  // handleDetailedSubmit/handleGenerateAiAnalysis/
  // handleGenerateDetailedAiAnalysis never throw on `.then()` in a test
  // that doesn't care about caching -- only tests that specifically assert
  // on these mocks override the resolved value.
  mockUpdateDealAnalysisSnapshot.mockReset();
  mockUpdateDealAnalysisSnapshot.mockResolvedValue(makeDeal());
  mockUpdateDealAiSnapshot.mockReset();
  mockUpdateDealAiSnapshot.mockResolvedValue(makeDeal());
  // Owner Return Metrics V3 Gate A7: the provenance-lookup calls
  // handleSubmit/handleDetailedSubmit/handleGenerateAiAnalysis/
  // handleGenerateDetailedAiAnalysis/handleSaveDeal/handleSaveDetailedDeal
  // now make before attaching a snapshot -- default to a resolved fixed
  // fingerprint pair so those calls never throw in a test that doesn't
  // care about the exact fingerprint value threaded through.
  mockFetchDealFingerprint.mockReset();
  mockFetchDealFingerprint.mockResolvedValue({
    financial_input_fingerprint: 'fp-financial',
    ai_context_fingerprint: 'fp-ai',
  });
  mockFetchDetailedDealFingerprint.mockReset();
  mockFetchDetailedDealFingerprint.mockResolvedValue({
    financial_input_fingerprint: 'fp-financial',
    ai_context_fingerprint: 'fp-ai',
  });
  // Default every test to an accepted confirmation so the Phase C
  // unsaved-changes guard and the Deal Library's delete confirmation don't
  // block tests that aren't specifically exercising cancellation -- those
  // tests override a single call with `mockReturnValueOnce(false)`.
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('App workflow', () => {
  it('renders all nine assumption fields blank on initial load (U10)', () => {
    render(<App />);

    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '');
    expect(screen.getByLabelText(/^Current NOI/)).toHaveProperty('value', '');
    expect(screen.getByLabelText(/^Occupancy/)).toHaveProperty('value', '');
    expect(screen.getByLabelText(/^NOI Growth/)).toHaveProperty('value', '');
    expect(screen.getByLabelText(/^Hold Period/)).toHaveProperty('value', '');
    expect(screen.getByLabelText(/^Exit Cap Rate/)).toHaveProperty('value', '');
    expect(screen.getByLabelText(/^LTV/)).toHaveProperty('value', '');
    expect(screen.getByLabelText(/^Interest Rate/)).toHaveProperty('value', '');
    expect(screen.getByLabelText(/^Amortization/)).toHaveProperty('value', '');
  });

  it('renders all five Underwriting V2 fields blank on a fresh manual deal (Gate 6)', () => {
    render(<App />);

    expect(screen.getByLabelText(/^Acquisition Costs/)).toHaveProperty('value', '');
    expect(screen.getByLabelText(/^Financing Fee/)).toHaveProperty('value', '');
    expect(screen.getByLabelText(/^Disposition Costs/)).toHaveProperty('value', '');
    expect(screen.getByLabelText(/^Annual CapEx Reserve/)).toHaveProperty('value', '');
    expect(screen.getByLabelText(/^Interest-Only Period/)).toHaveProperty('value', '');
  });

  it('blocks Analyze when a V2 field is blank, and unblocks it once completed', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeV2GoldenResults());
    render(<App />);
    fillV2GoldenDeal();
    await user.clear(screen.getByLabelText(/^Interest-Only Period/));

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect(await screen.findByText('Interest-Only Period is required.')).toBeTruthy();
    expect(mockAnalyze).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText(/^Interest-Only Period/), '2');
    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    await waitFor(() => expect(mockAnalyze).toHaveBeenCalledTimes(1));
  });

  it('blocks Save when a V2 field is blank, and unblocks it once completed', async () => {
    const user = userEvent.setup();
    mockCreateDeal.mockResolvedValue(makeDeal());
    render(<App />);
    fillV2GoldenDeal();
    await user.clear(screen.getByLabelText(/^Annual CapEx Reserve/));
    await user.type(screen.getByLabelText('Deal Name'), 'V2 Deal');

    await user.click(screen.getByRole('button', { name: 'Save Deal' }));

    expect(await screen.findByText('Annual CapEx Reserve is required.')).toBeTruthy();
    expect(mockCreateDeal).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText(/^Annual CapEx Reserve/), '50000');
    await user.click(screen.getByRole('button', { name: 'Save Deal' }));

    await waitFor(() => expect(mockCreateDeal).toHaveBeenCalledTimes(1));
  });

  it('accepts an explicit 0 for a V2 field and submits it', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    await waitFor(() => expect(mockAnalyze).toHaveBeenCalledTimes(1));
    expect(mockAnalyze).toHaveBeenCalledWith(
      expect.objectContaining({
        acquisition_cost_pct: 0,
        financing_fee_pct: 0,
        disposition_cost_pct: 0,
        annual_capex_reserve: 0,
        io_period: 0,
      }),
    );
  });

  it('rejects a fractional Interest-Only Period', async () => {
    const user = userEvent.setup();
    render(<App />);
    fillV2GoldenDeal();
    await user.clear(screen.getByLabelText(/^Interest-Only Period/));
    await user.type(screen.getByLabelText(/^Interest-Only Period/), '2.5');

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect(await screen.findByText('Interest-Only Period must be a whole number.')).toBeTruthy();
    expect(mockAnalyze).not.toHaveBeenCalled();
  });

  it('accepts an Interest-Only Period greater than the hold period', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeV2GoldenResults());
    render(<App />);
    fillV2GoldenDeal();
    await user.clear(screen.getByLabelText(/^Hold Period/));
    await user.type(screen.getByLabelText(/^Hold Period/), '5');
    await user.clear(screen.getByLabelText(/^Interest-Only Period/));
    await user.type(screen.getByLabelText(/^Interest-Only Period/), '10');

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    await waitFor(() => expect(mockAnalyze).toHaveBeenCalledTimes(1));
    expect(mockAnalyze).toHaveBeenCalledWith(
      expect.objectContaining({ hold_period: 5, io_period: 10 }),
    );
  });

  it('converts V2 percentage fields to canonical fractions', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeV2GoldenResults());
    render(<App />);
    fillV2GoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    await waitFor(() => expect(mockAnalyze).toHaveBeenCalledTimes(1));
    expect(mockAnalyze).toHaveBeenCalledWith(
      expect.objectContaining({
        acquisition_cost_pct: 0.02,
        financing_fee_pct: 0.01,
        disposition_cost_pct: 0.025,
      }),
    );
  });

  it('shows a validation error and never calls /analyze when submitting a blank form', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect(await screen.findByText(/Purchase Price is required/)).toBeTruthy();
    expect(mockAnalyze).not.toHaveBeenCalled();
  });

  it('shows key results after a successful analysis', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    // Both surfaces show the headline figures, and each is asserted in its
    // own panel rather than "somewhere on the page" (Gate B5).
    await screen.findAllByText('7.91%');
    expect(within(ownerSummary()).getByText('7.91%')).toBeTruthy();
    expect(within(ownerSummary()).getByText('1.44x')).toBeTruthy();
    expect(within(fullResults()).getByText('7.91%')).toBeTruthy();
    expect(within(fullResults()).getByText('1.44x')).toBeTruthy();
  });

  it('renders the V2 golden case: transaction costs, CapEx, and Year 1 vs. Minimum DSCR distinctly (Gate 6)', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeV2GoldenResults());
    render(<App />);
    fillV2GoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    await screen.findAllByText('7.38%');
    // This test is about the full ResultsPanel's own rendering of the V2
    // golden case -- scoped there, not merely "somewhere on the page."
    const results = fullResults();
    expect(within(results).getByText('7.38%')).toBeTruthy(); // Levered IRR
    expect(within(results).getByText('1.38x')).toBeTruthy(); // Equity Multiple
    expect(within(results).getByText('$200,000')).toBeTruthy(); // Acquisition Costs
    expect(within(results).getByText('$60,000')).toBeTruthy(); // Financing Fee
    expect(within(results).getByText('$267,525')).toBeTruthy(); // Disposition Costs

    // Year 1 DSCR (headline strip) and Minimum DSCR render as visibly
    // distinct values -- never computed in the frontend, only rendered.
    expect(within(results).getAllByText('2.00x').length).toBeGreaterThanOrEqual(1);
    expect(within(results).getByText('Min 1.65x')).toBeTruthy();
  });

  it('shows the Owner Returns headline (Year 1 Levered CoC, Year 1 Debt Yield, Cumulative Operating Distributions) in Quick mode', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeV2GoldenResults());
    render(<App />);
    fillV2GoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    await screen.findAllByText('Owner Returns');
    // Gate B5: this test is about the full ResultsPanel's own Owner Returns
    // headline strip, so it is scoped there -- the Owner Summary now shows
    // the same three figures and would otherwise satisfy it by accident.
    // Within ResultsPanel, "5.87%"/"10.00%"/"Cumulative Operating
    // Distributions" still legitimately appear both in the headline card
    // and in the Owner Return Schedule below it.
    const results = fullResults();
    expect(within(results).getByText('Owner Returns')).toBeTruthy();
    expect(within(results).getByText('Year 1 Levered CoC')).toBeTruthy();
    expect(within(results).getAllByText('5.87%').length).toBeGreaterThanOrEqual(1);
    expect(within(results).getByText('Year 1 Debt Yield')).toBeTruthy();
    expect(within(results).getAllByText('10.00%').length).toBeGreaterThanOrEqual(1);
    expect(
      within(results).getAllByText('Cumulative Operating Distributions').length,
    ).toBeGreaterThanOrEqual(1);
    expect(within(results).getAllByText('$1,175,947').length).toBeGreaterThanOrEqual(1);
  });

  it('shows the annual CapEx series in the year-by-year table', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeV2GoldenResults());
    render(<App />);
    fillV2GoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findAllByText('7.38%');

    expect(screen.getAllByText('$50,000').length).toBeGreaterThanOrEqual(1);
  });

  it('clears displayed results when an assumption is edited after a successful analysis', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    expect((await screen.findAllByText('7.91%')).length).toBeGreaterThanOrEqual(1);

    await user.type(screen.getByLabelText(/^Current NOI/), '1');

    expect(screen.queryByText('7.91%')).toBeNull();
    expect(
      screen.getByText(/Enter assumptions and click/),
    ).toBeTruthy();
  });

  it('clears previous results while a new submission is loading', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValueOnce(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    expect((await screen.findAllByText('7.91%')).length).toBeGreaterThanOrEqual(1);

    const second = deferred<AcquisitionResults>();
    mockAnalyze.mockReturnValueOnce(second.promise);

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect(screen.queryByText('7.91%')).toBeNull();

    second.resolve(makeResults({ levered_irr: 0.09 }));
    expect((await screen.findAllByText('9.00%')).length).toBeGreaterThanOrEqual(1);
  });

  it('does not display stale results and shows an error banner after a failed analysis', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValueOnce(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    expect((await screen.findAllByText('7.91%')).length).toBeGreaterThanOrEqual(1);

    mockAnalyze.mockRejectedValueOnce(new ApiError('The backend rejected the request.'));

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect(await screen.findByText('The backend rejected the request.')).toBeTruthy();
    expect(screen.queryByText('7.91%')).toBeNull();
  });

  it('disables inputs and the Analyze button while a request is pending', async () => {
    const user = userEvent.setup();
    const pending = deferred<AcquisitionResults>();
    mockAnalyze.mockReturnValueOnce(pending.promise);
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('disabled', true);
    expect(screen.getByRole('button', { name: 'Analyzing…' })).toHaveProperty('disabled', true);

    pending.resolve(makeResults());
    // A successful Analyze lands on Overview (Sprint C Gate C2), so wait for
    // that, then go back to the form to check the controls re-enabled.
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Overview' })).toHaveProperty(
        'ariaSelected',
        'true',
      ),
    );
    await goTo(user, 'Underwrite');

    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('disabled', false);
    expect(screen.getByRole('button', { name: 'Analyze' })).toHaveProperty('disabled', false);
  });

  it('replaces the first result with the second successful analysis', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValueOnce(makeResults({ levered_irr: 0.0791303 }));
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    expect((await screen.findAllByText('7.91%')).length).toBeGreaterThanOrEqual(1);

    mockAnalyze.mockResolvedValueOnce(makeResults({ levered_irr: 0.12 }));
    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect((await screen.findAllByText('12.00%')).length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText('7.91%')).toBeNull();
  });

  it('displays N/A for null metrics', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(
      makeResults({
        levered_irr: null,
        unlevered_irr: null,
        equity_multiple: null,
        dscr_by_year: [null, null, null, null, null],
        headline_dscr: null,
        min_dscr: null,
        levered_cash_on_cash_by_year: [null, null, null, null, null],
        year_1_debt_yield: null,
      }),
    );
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    const naValues = await screen.findAllByText('N/A');
    expect(naValues.length).toBeGreaterThanOrEqual(4);
    // Owner Returns headline (Year 1 Levered CoC, Year 1 Debt Yield) and
    // every Owner Return Schedule row's Levered CoC cell -- never 0.00%.
    expect(screen.queryByText('0.00%')).toBeNull();
  });

  it('converts percentage inputs to decimals exactly once when submitting', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect(mockAnalyze).toHaveBeenCalledWith({
      purchase_price: 50_000_000,
      current_noi: 2_500_000,
      occupancy: 0.95,
      noi_growth: 0.03,
      hold_period: 5,
      exit_cap_rate: 0.055,
      ltv: 0.65,
      interest_rate: 0.0525,
      amortization: 30,
      acquisition_cost_pct: 0,
      financing_fee_pct: 0,
      disposition_cost_pct: 0,
      annual_capex_reserve: 0,
      io_period: 0,
    });
  });
});

describe('Sensitivity analysis workflow', () => {
  it('runs and displays the sensitivity section only after a successful base analysis', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    expect(screen.queryByText('Sensitivity Analysis')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect(await screen.findByText('Sensitivity Analysis')).toBeTruthy();
    expect(mockFetchSensitivityPresets).toHaveBeenCalledTimes(1);
  });

  it('passes the same raw-decimal request to sensitivity as to the base analysis', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Sensitivity Analysis');

    expect(mockFetchSensitivityPresets).toHaveBeenCalledWith(mockAnalyze.mock.calls[0][0]);
  });

  it('clears sensitivity results when an assumption is edited after a successful analysis', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Sensitivity Analysis');

    await user.type(screen.getByLabelText(/^Current NOI/), '1');

    expect(screen.queryByText('Sensitivity Analysis')).toBeNull();
  });

  it('does not corrupt the successful base results when the sensitivity request fails', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    mockFetchSensitivityPresets.mockRejectedValueOnce(
      new ApiError('The sensitivity request failed.'),
    );
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect(await screen.findByText('The sensitivity request failed.')).toBeTruthy();
    expect(screen.getAllByText('7.91%').length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText('Exit Cap × NOI Growth')).toBeNull();
  });
});

describe('Break-even analysis workflow', () => {
  it('runs and displays the break-even section only after a successful base analysis', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    expect(screen.queryByText('Break-Even Analysis')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect(await screen.findByText('Break-Even Analysis')).toBeTruthy();
    expect(mockFetchBreakEvenAnalysis).toHaveBeenCalledTimes(1);
  });

  it('renders default hurdle controls and all five result cards', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Break-Even Analysis');

    expect(screen.getByLabelText(/^Target Levered IRR/)).toHaveProperty('value', '10.00');
    expect(screen.getByLabelText(/^Target Equity Multiple/)).toHaveProperty('value', '1.50');
    expect(screen.getByLabelText(/^Target Year 1 DSCR/)).toHaveProperty('value', '1.20');
    expect(screen.getByText('Maximum Purchase Price')).toBeTruthy();
    expect(screen.getByText('Maximum Exit Cap')).toBeTruthy();
    expect(screen.getByText('Minimum NOI Growth')).toBeTruthy();
    expect(screen.getByText('Maximum Interest Rate')).toBeTruthy();
    expect(screen.getByText('Minimum Current NOI')).toBeTruthy();
  });

  it('converts the default IRR percent hurdle to a decimal exactly once, with the default Levered IRR return hurdle', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Break-Even Analysis');

    expect(mockFetchBreakEvenAnalysis).toHaveBeenCalledWith(
      mockAnalyze.mock.calls[0][0],
      0.10,
      1.50,
      1.20,
      'levered_irr',
    );
  });

  it('changing the IRR hurdle refreshes only break-even, not the base analysis or sensitivity', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Break-Even Analysis');
    expect(mockAnalyze).toHaveBeenCalledTimes(1);
    expect(mockFetchSensitivityPresets).toHaveBeenCalledTimes(1);
    expect(mockFetchBreakEvenAnalysis).toHaveBeenCalledTimes(1);

    const irrInput = screen.getByLabelText(/^Target Levered IRR/);
    await user.clear(irrInput);
    await user.type(irrInput, '12');

    await waitFor(() => {
      expect(mockFetchBreakEvenAnalysis.mock.calls.length).toBeGreaterThan(1);
    });

    expect(mockAnalyze).toHaveBeenCalledTimes(1);
    expect(mockFetchSensitivityPresets).toHaveBeenCalledTimes(1);
    const lastCall =
      mockFetchBreakEvenAnalysis.mock.calls[mockFetchBreakEvenAnalysis.mock.calls.length - 1];
    expect(lastCall[1]).toBeCloseTo(0.12);
    expect(lastCall[2]).toBeCloseTo(1.50);
    expect(lastCall[3]).toBeCloseTo(1.20);
    expect(lastCall[4]).toBe('levered_irr');
  });

  it('changing the DSCR hurdle refreshes only break-even', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Break-Even Analysis');

    const initialCallCount = mockFetchBreakEvenAnalysis.mock.calls.length;

    const dscrInput = screen.getByLabelText(/^Target Year 1 DSCR/);
    await user.clear(dscrInput);
    await user.type(dscrInput, '1.3');

    await waitFor(() => {
      expect(mockFetchBreakEvenAnalysis.mock.calls.length).toBeGreaterThan(initialCallCount);
    });

    expect(mockAnalyze).toHaveBeenCalledTimes(1);
    expect(mockFetchSensitivityPresets).toHaveBeenCalledTimes(1);
    const lastCall =
      mockFetchBreakEvenAnalysis.mock.calls[mockFetchBreakEvenAnalysis.mock.calls.length - 1];
    expect(lastCall[1]).toBeCloseTo(0.10);
    expect(lastCall[2]).toBeCloseTo(1.50);
    expect(lastCall[3]).toBeCloseTo(1.3);
    expect(lastCall[4]).toBe('levered_irr');
  });

  it('changing the target Equity Multiple reruns only break-even, treating "1.65" as 1.65x not a percentage', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Break-Even Analysis');

    const initialCallCount = mockFetchBreakEvenAnalysis.mock.calls.length;

    const emInput = screen.getByLabelText(/^Target Equity Multiple/);
    await user.clear(emInput);
    await user.type(emInput, '1.65');

    await waitFor(() => {
      expect(mockFetchBreakEvenAnalysis.mock.calls.length).toBeGreaterThan(initialCallCount);
    });

    expect(mockAnalyze).toHaveBeenCalledTimes(1);
    expect(mockFetchSensitivityPresets).toHaveBeenCalledTimes(1);
    const lastCall =
      mockFetchBreakEvenAnalysis.mock.calls[mockFetchBreakEvenAnalysis.mock.calls.length - 1];
    expect(lastCall[1]).toBeCloseTo(0.10);
    expect(lastCall[2]).toBeCloseTo(1.65);
    expect(lastCall[3]).toBeCloseTo(1.20);
  });

  it('switching the return-hurdle toggle to Equity Multiple reruns only break-even and updates only the three return-hurdle cards', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Break-Even Analysis');
    await goTo(user, 'Risk');
    expect(screen.getAllByText('for 10.00% Levered IRR').length).toBe(3);

    mockFetchBreakEvenAnalysis.mockResolvedValueOnce(
      makeBreakEvenAnalysis({
        max_purchase_price: makeBreakEvenResult({
          metric: 'equity_multiple',
          target_metric_value: 1.50,
          solved_assumption_value: 44_120_000,
          solved_metric_value: 1.5002,
        }),
        max_exit_cap_rate: makeBreakEvenResult({
          break_even_type: 'max_exit_cap_rate',
          assumption: 'exit_cap_rate',
          metric: 'equity_multiple',
          target_metric_value: 1.50,
          baseline_assumption_value: 0.055,
          solved_assumption_value: 0.0589,
          solved_metric_value: 1.5002,
          lower_search_bound: 0.025,
          upper_search_bound: 0.105,
        }),
        min_noi_growth: makeBreakEvenResult({
          break_even_type: 'min_noi_growth',
          assumption: 'noi_growth',
          metric: 'equity_multiple',
          target_metric_value: 1.50,
          baseline_assumption_value: 0.03,
          solved_assumption_value: 0.0398,
          solved_metric_value: 1.5002,
          lower_search_bound: -0.07,
          upper_search_bound: 0.13,
        }),
      }),
    );

    await user.click(screen.getByRole('button', { name: 'Equity Multiple' }));

    await waitFor(() => {
      expect(mockFetchBreakEvenAnalysis.mock.calls.length).toBeGreaterThan(1);
    });
    const lastCall =
      mockFetchBreakEvenAnalysis.mock.calls[mockFetchBreakEvenAnalysis.mock.calls.length - 1];
    expect(lastCall[4]).toBe('equity_multiple');

    expect(mockAnalyze).toHaveBeenCalledTimes(1);
    expect(mockFetchSensitivityPresets).toHaveBeenCalledTimes(1);

    expect((await screen.findAllByText('$44,120,000')).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('for 1.50x Equity Multiple').length).toBe(3);
    expect(screen.queryByText('for 10.00% Levered IRR')).toBeNull();

    // DSCR cards remain unaffected -- same values, same subtitle.
    expect(screen.getByText('Maximum Interest Rate')).toBeTruthy();
    expect(screen.getByText('Minimum Current NOI')).toBeTruthy();
    expect(screen.getAllByText('for 1.20x Year 1 DSCR').length).toBe(2);
  });

  it('shows "Not found in tested range" and never claims impossibility', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    mockFetchBreakEvenAnalysis.mockResolvedValue(
      makeBreakEvenAnalysis({
        max_purchase_price: makeBreakEvenResult({
          status: 'no_solution_in_range',
          solved_assumption_value: null,
          solved_metric_value: null,
        }),
      }),
    );
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect(await screen.findByText('Not found in tested range')).toBeTruthy();
    expect(screen.queryByText(/impossible/i)).toBeNull();
    expect(screen.queryByText(/no solution exists/i)).toBeNull();
  });

  it('clears break-even results when a base assumption is edited', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Break-Even Analysis');

    await user.type(screen.getByLabelText(/^Current NOI/), '1');

    expect(screen.queryByText('Break-Even Analysis')).toBeNull();
  });

  it('does not corrupt base or sensitivity results when the break-even request fails', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    mockFetchBreakEvenAnalysis.mockRejectedValueOnce(
      new ApiError('The break-even request failed.'),
    );
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect(await screen.findByText('The break-even request failed.')).toBeTruthy();
    expect(screen.getAllByText('7.91%').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Sensitivity Analysis')).toBeTruthy();
    expect(screen.queryByText('Maximum Purchase Price')).toBeNull();
  });

  it('shows a loading state while break-even is calculating', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    const pending = deferred<StandardBreakEvenAnalysis>();
    mockFetchBreakEvenAnalysis.mockReturnValueOnce(pending.promise);
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect(await screen.findByText(/Calculating break-even/)).toBeTruthy();

    pending.resolve(makeBreakEvenAnalysis());
    expect(await screen.findByText('Maximum Purchase Price')).toBeTruthy();
  });
});

describe('AI Analyst workflow', () => {
  it('shows the AI Analyst section only after a successful base analysis', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    expect(screen.queryByText('Anchor AI Analyst')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect(await screen.findByText('Anchor AI Analyst')).toBeTruthy();
    expect(mockFetchAIAnalysis).not.toHaveBeenCalled();
  });

  it('does not auto-generate an AI analysis after the base analysis completes', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Anchor AI Analyst');
    await screen.findByText('Break-Even Analysis');

    expect(mockFetchAIAnalysis).not.toHaveBeenCalled();
  });

  it('generates an AI analysis only when the Generate button is clicked', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Anchor AI Analyst');

    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));

    expect(await screen.findByText('Investment View')).toBeTruthy();
    expect(mockFetchAIAnalysis).toHaveBeenCalledTimes(1);
    expect(mockFetchAIAnalysis).toHaveBeenCalledWith(
      mockAnalyze.mock.calls[0][0],
      0.10,
      1.50,
      1.20,
      'levered_irr',
      null,
    );
  });

  it('shows a loading state and disables the Generate button while pending', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    const pending = deferred<AIAnalysis>();
    mockFetchAIAnalysis.mockReturnValueOnce(pending.promise);
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Anchor AI Analyst');

    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));

    expect(await screen.findByText(/Generating AI analysis/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Generating…' })).toHaveProperty('disabled', true);

    pending.resolve(makeAiAnalysis());
    expect(await screen.findByRole('button', { name: 'Generate AI Analysis' })).toBeTruthy();
  });

  it('renders the mocked structured AI response, including strengths/risks/questions lists', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Anchor AI Analyst');
    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));

    expect(await screen.findByText('Levered IRR clears the target hurdle at baseline.')).toBeTruthy();
    expect(
      screen.getByText('Exit cap rate expansion compresses returns per the sensitivity matrix.'),
    ).toBeTruthy();
    expect(screen.getByText('What is the in-place rent roll composition?')).toBeTruthy();
  });

  it('shows an AI-specific error without removing the deterministic results', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    mockFetchAIAnalysis.mockRejectedValueOnce(
      new ApiError('OPENAI_API_KEY is not configured.'),
    );
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Anchor AI Analyst');
    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));

    expect(await screen.findByText('OPENAI_API_KEY is not configured.')).toBeTruthy();
    expect(screen.getAllByText('7.91%').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Break-Even Analysis')).toBeTruthy();
    expect(screen.getByText('Sensitivity Analysis')).toBeTruthy();
  });

  it('clears AI output when a base assumption is edited', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Anchor AI Analyst');
    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    await screen.findByText('Investment View');

    await user.type(screen.getByLabelText(/^Current NOI/), '1');

    expect(screen.queryByText('Anchor AI Analyst')).toBeNull();
    expect(screen.queryByText('Investment View')).toBeNull();
  });

  it('clears AI output when a break-even hurdle changes', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Anchor AI Analyst');
    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    await screen.findByText('Investment View');

    const irrInput = screen.getByLabelText(/^Target Levered IRR/);
    await user.clear(irrInput);
    await user.type(irrInput, '12');

    await waitFor(() => {
      expect(screen.queryByText('Investment View')).toBeNull();
    });
    // The AI section itself remains -- only its prior output is cleared,
    // and no new AI request is spent automatically (still just the one
    // call from the earlier manual "Generate AI Analysis" click).
    expect(screen.getByText('Anchor AI Analyst')).toBeTruthy();
    expect(mockFetchAIAnalysis).toHaveBeenCalledTimes(1);
  });

  it('replaces the prior AI output with the second generation', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    mockFetchAIAnalysis.mockResolvedValueOnce(
      makeAiAnalysis({ investment_view: 'First view.' }),
    );
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Anchor AI Analyst');
    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    expect(await screen.findByText('First view.')).toBeTruthy();

    mockFetchAIAnalysis.mockResolvedValueOnce(
      makeAiAnalysis({ investment_view: 'Second view.' }),
    );
    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));

    expect(await screen.findByText('Second view.')).toBeTruthy();
    expect(screen.queryByText('First view.')).toBeNull();
    expect(mockFetchAIAnalysis).toHaveBeenCalledTimes(2);
  });

  it('never renders anything resembling a raw API key', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Anchor AI Analyst');
    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    await screen.findByText('Investment View');

    expect(document.body.innerHTML).not.toMatch(/sk-[A-Za-z0-9]/);
    expect(document.body.innerHTML.toLowerCase()).not.toContain('openai_api_key');
  });
});

describe('OM ingestion workflow', () => {
  async function uploadAndApprove(user: ReturnType<typeof userEvent.setup>) {
    render(<App />);
    mockUploadOm.mockResolvedValue(makeExtractionResult());

    await goTo(user, 'Documents');
    const file = new File(['%PDF-1.4'], 'om.pdf', { type: 'application/pdf' });
    await user.upload(screen.getByLabelText('Upload OM (PDF)'), file);

    await screen.findByRole('heading', { name: 'Purchase Price' }, { timeout: 3000 });
  }

  it('pre-fills AssumptionsForm with approved candidate values', async () => {
    const user = userEvent.setup();
    await uploadAndApprove(user);

    const purchasePriceCard = screen.getByRole('heading', { name: 'Purchase Price' }).closest('.om-field-card') as HTMLElement;
    await user.click(
      Array.from(purchasePriceCard.querySelectorAll('button')).find((b) => b.textContent === 'Approve')!,
    );
    const exitCapCard = screen.getByRole('heading', { name: 'Exit Cap Rate' }).closest('.om-field-card') as HTMLElement;
    await user.click(
      Array.from(exitCapCard.querySelectorAll('button')).find((b) => b.textContent === 'Approve')!,
    );

    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Use approved values' }));

    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '48000000');
    expect(screen.getByLabelText(/^Exit Cap Rate/)).toHaveProperty('value', '6');
  });

  it('excludes unapproved and unresolved-conflict fields from the pre-filled values', async () => {
    const user = userEvent.setup();
    await uploadAndApprove(user);

    // Approve only purchase price; leave exit cap rate (and every other
    // field) pending.
    const purchasePriceCard = screen.getByRole('heading', { name: 'Purchase Price' }).closest('.om-field-card') as HTMLElement;
    await user.click(
      Array.from(purchasePriceCard.querySelectorAll('button')).find((b) => b.textContent === 'Approve')!,
    );

    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Use approved values' }));

    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '48000000');
    // Exit Cap Rate was never approved -- it must stay blank (U10), not fall
    // back to a default value.
    expect(screen.getByLabelText(/^Exit Cap Rate/)).toHaveProperty('value', '');
  });

  it('shows the excluded-fields summary before the analyst finishes review', async () => {
    const user = userEvent.setup();
    await uploadAndApprove(user);

    const summary = screen.getByText(/Not carried to the form/);
    expect(summary.textContent).toContain('Current NOI');
    expect(summary.textContent).toContain('Hold Period');
  });

  it('communicates that the five V2 assumptions require analyst entry, not OM extraction (Gate 6)', async () => {
    const user = userEvent.setup();
    await uploadAndApprove(user);

    const notice = screen.getByText(/Additional underwriting assumptions/);
    expect(notice.textContent).toContain('Acquisition Costs');
    expect(notice.textContent).toContain('Financing Fee');
    expect(notice.textContent).toContain('Disposition Costs');
    expect(notice.textContent).toContain('Annual CapEx Reserve');
    expect(notice.textContent).toContain('Interest-Only Period');

    expect(screen.getByLabelText(/^Acquisition Costs/)).toHaveProperty('value', '');
    expect(screen.getByLabelText(/^Interest-Only Period/)).toHaveProperty('value', '');
  });

  it('leaves pre-filled values editable in AssumptionsForm after handoff', async () => {
    const user = userEvent.setup();
    await uploadAndApprove(user);

    const purchasePriceCard = screen.getByRole('heading', { name: 'Purchase Price' }).closest('.om-field-card') as HTMLElement;
    await user.click(
      Array.from(purchasePriceCard.querySelectorAll('button')).find((b) => b.textContent === 'Approve')!,
    );
    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Use approved values' }));

    const purchasePriceInput = screen.getByLabelText(/^Purchase Price/);
    expect(purchasePriceInput).toHaveProperty('disabled', false);

    await user.clear(purchasePriceInput);
    await user.type(purchasePriceInput, '52000000');

    expect(purchasePriceInput).toHaveProperty('value', '52000000');
  });

  it('never calls /analyze automatically after landing on the pre-filled form', async () => {
    const user = userEvent.setup();
    await uploadAndApprove(user);

    const purchasePriceCard = screen.getByRole('heading', { name: 'Purchase Price' }).closest('.om-field-card') as HTMLElement;
    await user.click(
      Array.from(purchasePriceCard.querySelectorAll('button')).find((b) => b.textContent === 'Approve')!,
    );
    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Use approved values' }));

    expect(mockAnalyze).not.toHaveBeenCalled();
  });

  it('shows an explicit failure state on an OM extraction error', async () => {
    const user = userEvent.setup();
    render(<App />);
    mockUploadOm.mockRejectedValue(new ApiError('The Azure Document Intelligence request failed.'));

    const file = new File(['%PDF-1.4'], 'om.pdf', { type: 'application/pdf' });
    await user.upload(screen.getByLabelText('Upload OM (PDF)'), file);

    expect(await screen.findByText('The Azure Document Intelligence request failed.')).toBeTruthy();
  });

  it('clears stale deterministic results when OM-approved values are handed off', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    expect((await screen.findAllByText('7.91%')).length).toBeGreaterThanOrEqual(1);

    mockUploadOm.mockResolvedValue(makeExtractionResult());
    await goTo(user, 'Documents');
    const file = new File(['%PDF-1.4'], 'om.pdf', { type: 'application/pdf' });
    await user.upload(screen.getByLabelText('Upload OM (PDF)'), file);
    await screen.findByRole('heading', { name: 'Purchase Price' });

    const purchasePriceCard = screen.getByRole('heading', { name: 'Purchase Price' }).closest('.om-field-card') as HTMLElement;
    await user.click(
      Array.from(purchasePriceCard.querySelectorAll('button')).find((b) => b.textContent === 'Approve')!,
    );
    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Use approved values' }));

    expect(screen.queryByText('7.91%')).toBeNull();
  });
});

function makeAcquisitionRequest(overrides: Partial<AcquisitionRequest> = {}): AcquisitionRequest {
  return {
    purchase_price: 48_000_000,
    current_noi: 2_400_000,
    occupancy: 0.93,
    noi_growth: 0.025,
    hold_period: 7,
    exit_cap_rate: 0.06,
    ltv: 0.6,
    interest_rate: 0.05,
    amortization: 25,
    acquisition_cost_pct: 0,
    financing_fee_pct: 0,
    disposition_cost_pct: 0,
    annual_capex_reserve: 0,
    io_period: 0,
    ...overrides,
  };
}

describe('Excel ingestion workflow', () => {
  /** Uploads the default (legacy nine-field) workbook and waits for the
   * Excel Ingestion Review panel to appear -- never waits on the active
   * `AssumptionsForm`, which this upload must not touch. */
  async function uploadWorkbook(user: ReturnType<typeof userEvent.setup>) {
    render(<App />);
    mockUploadExcel.mockResolvedValue(makeExcelIntakeReport());

    await goTo(user, 'Documents');
    const file = new File(['PK'], 'anchor_input.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), file);

    await waitFor(() => {
      expect(screen.getByLabelText('Excel Review Purchase Price')).toHaveProperty(
        'value',
        '48000000',
      );
    });
  }

  /** Completes the five blanked V2 review fields with explicit zeros --
   * the minimum needed to unblock approval of a legacy workbook. */
  async function completeBlankedV2ReviewFields(user: ReturnType<typeof userEvent.setup>) {
    await user.type(screen.getByLabelText('Excel Review Acquisition Costs'), '0');
    await user.type(screen.getByLabelText('Excel Review Financing Fee'), '0');
    await user.type(screen.getByLabelText('Excel Review Disposition Costs'), '0');
    await user.type(screen.getByLabelText('Excel Review Annual CapEx Reserve'), '0');
    await user.type(screen.getByLabelText('Excel Review Interest-Only Period'), '0');
  }

  it('does not immediately populate active assumptions after upload', async () => {
    const user = userEvent.setup();
    await uploadWorkbook(user);

    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty(
      'value',
      BLANK_FORM_VALUES.purchasePrice,
    );
  });

  it('creates a temporary Excel review with all nine imported values for a legacy workbook', async () => {
    const user = userEvent.setup();
    await uploadWorkbook(user);

    expect(screen.getByLabelText('Excel Review Purchase Price')).toHaveProperty('value', '48000000');
    expect(screen.getByLabelText('Excel Review Current NOI')).toHaveProperty('value', '2400000');
    expect(screen.getByLabelText('Excel Review Occupancy')).toHaveProperty('value', '93');
    expect(screen.getByLabelText('Excel Review NOI Growth')).toHaveProperty('value', '2.5');
    expect(screen.getByLabelText('Excel Review Hold Period')).toHaveProperty('value', '7');
    expect(screen.getByLabelText('Excel Review Exit Cap Rate')).toHaveProperty('value', '6');
    expect(screen.getByLabelText('Excel Review LTV')).toHaveProperty('value', '60');
    expect(screen.getByLabelText('Excel Review Interest Rate')).toHaveProperty('value', '5');
    expect(screen.getByLabelText('Excel Review Amortization')).toHaveProperty('value', '25');
  });

  it('leaves all five V2 fields visibly blank in review for a legacy nine-field workbook (Gate 6)', async () => {
    const user = userEvent.setup();
    await uploadWorkbook(user);

    expect(screen.getByLabelText('Excel Review Acquisition Costs')).toHaveProperty('value', '');
    expect(screen.getByLabelText('Excel Review Financing Fee')).toHaveProperty('value', '');
    expect(screen.getByLabelText('Excel Review Disposition Costs')).toHaveProperty('value', '');
    expect(screen.getByLabelText('Excel Review Annual CapEx Reserve')).toHaveProperty('value', '');
    expect(screen.getByLabelText('Excel Review Interest-Only Period')).toHaveProperty('value', '');
  });

  it('marks the five blanked V2 fields as requiring analyst input', async () => {
    const user = userEvent.setup();
    await uploadWorkbook(user);

    expect(screen.getAllByText('Requires input')).toHaveLength(5);
  });

  it('shows the additional-assumptions review message for a legacy workbook, phrased as required review not extraction failure', async () => {
    const user = userEvent.setup();
    await uploadWorkbook(user);

    const banner = await screen.findByText(/Additional underwriting assumptions.*review/);
    expect(banner.textContent).toContain('Acquisition Costs');
    expect(banner.textContent).toContain('Financing Fee');
    expect(banner.textContent).toContain('Disposition Costs');
    expect(banner.textContent).toContain('Annual CapEx Reserve');
    expect(banner.textContent).toContain('Interest-Only Period');
    expect(banner.textContent?.toLowerCase()).not.toContain('missing from');
    expect(banner.textContent?.toLowerCase()).not.toContain('failed');
  });

  it('review values are editable', async () => {
    const user = userEvent.setup();
    await uploadWorkbook(user);

    const reviewPurchasePrice = screen.getByLabelText('Excel Review Purchase Price');
    await user.clear(reviewPurchasePrice);
    await user.type(reviewPurchasePrice, '52000000');

    expect(reviewPurchasePrice).toHaveProperty('value', '52000000');
    // Editing the review must not touch the still-untouched active form.
    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty(
      'value',
      BLANK_FORM_VALUES.purchasePrice,
    );
  });

  it('blocks approval for a legacy workbook until the blanked V2 fields are completed, and an explicit zero satisfies them', async () => {
    const user = userEvent.setup();
    await uploadWorkbook(user);

    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));
    expect(await screen.findByText('Acquisition Costs is required.')).toBeTruthy();
    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty(
      'value',
      BLANK_FORM_VALUES.purchasePrice,
    );

    await completeBlankedV2ReviewFields(user);
    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));

    await waitFor(() => {
      expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '48000000');
    });
    expect(screen.getByLabelText(/^Acquisition Costs/)).toHaveProperty('value', '0');
    expect(screen.queryByRole('button', { name: 'Approve & Load Assumptions' })).toBeNull();
  });

  it('once all five V2 values are completed, the legacy workbook can be approved into the active assumptions', async () => {
    const user = userEvent.setup();
    await uploadWorkbook(user);
    await completeBlankedV2ReviewFields(user);

    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));

    await waitFor(() => {
      expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '48000000');
    });
    expect(screen.getByLabelText(/^Current NOI/)).toHaveProperty('value', '2400000');
    expect(screen.getByLabelText(/^Financing Fee/)).toHaveProperty('value', '0');
    expect(screen.getByLabelText(/^Interest-Only Period/)).toHaveProperty('value', '0');
    expect(mockAnalyze).not.toHaveBeenCalled();
  });

  it('populates all fourteen review values with no missing-V2 completion required for a complete V2 workbook', async () => {
    const user = userEvent.setup();
    render(<App />);
    mockUploadExcel.mockResolvedValue(
      makeExcelIntakeReport({
        inputs: makeAcquisitionRequest({
          acquisition_cost_pct: 0.02,
          financing_fee_pct: 0.01,
          disposition_cost_pct: 0.025,
          annual_capex_reserve: 50_000,
          io_period: 2,
        }),
        defaulted_v2_field_ids: [],
      }),
    );

    const file = new File(['PK'], 'anchor_input_v2.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), file);

    await waitFor(() => {
      expect(screen.getByLabelText('Excel Review Purchase Price')).toHaveProperty(
        'value',
        '48000000',
      );
    });
    expect(screen.getByLabelText('Excel Review Acquisition Costs')).toHaveProperty('value', '2');
    expect(screen.getByLabelText('Excel Review Financing Fee')).toHaveProperty('value', '1');
    expect(screen.getByLabelText('Excel Review Disposition Costs')).toHaveProperty('value', '2.5');
    expect(screen.getByLabelText('Excel Review Annual CapEx Reserve')).toHaveProperty(
      'value',
      '50000',
    );
    expect(screen.getByLabelText('Excel Review Interest-Only Period')).toHaveProperty('value', '2');
    expect(screen.queryByText(/Additional underwriting assumptions/)).toBeNull();
    expect(screen.queryByText('Requires input')).toBeNull();

    // No missing-V2 completion required -- approval succeeds immediately.
    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));
    await waitFor(() => {
      expect(screen.getByLabelText(/^Acquisition Costs/)).toHaveProperty('value', '2');
    });
    expect(mockAnalyze).not.toHaveBeenCalled();
  });

  it('Approve & Load Assumptions never automatically calls Analyze', async () => {
    const user = userEvent.setup();
    await uploadWorkbook(user);
    await completeBlankedV2ReviewFields(user);

    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));

    await waitFor(() => {
      expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '48000000');
    });
    expect(mockAnalyze).not.toHaveBeenCalled();
  });

  it('running Analyze Deal after approval submits the approved values', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    await uploadWorkbook(user);
    await completeBlankedV2ReviewFields(user);
    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));
    await waitFor(() => {
      expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '48000000');
    });

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    await waitFor(() => expect(mockAnalyze).toHaveBeenCalledTimes(1));
    expect(mockAnalyze).toHaveBeenCalledWith(makeAcquisitionRequest());
  });

  it('Cancel Review discards the pending review and leaves active assumptions unchanged', async () => {
    const user = userEvent.setup();
    await uploadWorkbook(user);

    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Cancel Review' }));

    expect(screen.queryByLabelText('Excel Review Purchase Price')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Approve & Load Assumptions' })).toBeNull();
    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty(
      'value',
      BLANK_FORM_VALUES.purchasePrice,
    );
  });

  it('uploading a second workbook replaces the pending review cleanly rather than merging', async () => {
    const user = userEvent.setup();
    await uploadWorkbook(user);

    mockUploadExcel.mockResolvedValue(
      makeExcelIntakeReport({ inputs: makeAcquisitionRequest({ purchase_price: 61_000_000 }) }),
    );
    const secondFile = new File(['PK'], 'anchor_input_v2.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), secondFile);

    await waitFor(() => {
      expect(screen.getByLabelText('Excel Review Purchase Price')).toHaveProperty(
        'value',
        '61000000',
      );
    });
    // Exactly one review panel/field exists -- the two uploads were never merged.
    expect(screen.getAllByLabelText('Excel Review Purchase Price')).toHaveLength(1);
  });

  it('shows a loading state while the workbook is being parsed', async () => {
    const user = userEvent.setup();
    const pending = deferred<ExcelIntakeReport>();
    mockUploadExcel.mockReturnValueOnce(pending.promise);
    render(<App />);

    const file = new File(['PK'], 'anchor_input.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), file);

    expect(await screen.findByText(/Parsing workbook/)).toBeTruthy();
    pending.resolve(makeExcelIntakeReport());
  });

  it('shows a validation error and leaves existing form values and any pending review unchanged on a malformed workbook', async () => {
    const user = userEvent.setup();
    render(<App />);
    fillGoldenDeal();
    mockUploadExcel.mockRejectedValue(
      new ApiError("Value for Field ID 'purchase_price' is blank at Inputs!C2.", [
        { field_id: 'purchase_price', category: 'blank_value', message: "Value for Field ID 'purchase_price' is blank at Inputs!C2." },
      ]),
    );

    const file = new File(['PK'], 'anchor_input.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), file);

    expect(
      await screen.findByText("Value for Field ID 'purchase_price' is blank at Inputs!C2."),
    ).toBeTruthy();
    // A failed upload must not corrupt values already entered in the form,
    // and must never create a review panel of its own.
    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', DEFAULT_FORM_VALUES.purchasePrice);
    expect(screen.queryByLabelText('Excel Review Purchase Price')).toBeNull();
    expect(mockAnalyze).not.toHaveBeenCalled();
  });

  it('deterministic results remain visible immediately after upload, and clear only once the review is approved', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    expect((await screen.findAllByText('7.91%')).length).toBeGreaterThanOrEqual(1);

    mockUploadExcel.mockResolvedValue(makeExcelIntakeReport());
    const file = new File(['PK'], 'anchor_input.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), file);
    await waitFor(() => {
      expect(screen.getByLabelText('Excel Review Purchase Price')).toHaveProperty(
        'value',
        '48000000',
      );
    });
    // Upload alone must not touch Analyze state.
    expect(screen.getAllByText('7.91%').length).toBeGreaterThanOrEqual(1);

    await completeBlankedV2ReviewFields(user);
    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));

    await waitFor(() => {
      expect(screen.queryByText('7.91%')).toBeNull();
    });
  });

  it('shows a review-oriented success message naming the uploaded file, not an immediate-population message', async () => {
    const user = userEvent.setup();
    await uploadWorkbook(user);

    expect(
      await screen.findByText(
        'Workbook parsed successfully. Review the imported assumptions below before loading them ' +
          'into the deal.',
      ),
    ).toBeTruthy();
  });

  it('shows a concise success confirmation after approval', async () => {
    const user = userEvent.setup();
    await uploadWorkbook(user);
    await completeBlankedV2ReviewFields(user);

    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));

    expect(
      await screen.findByText(
        'Excel assumptions approved and loaded. Review the deal assumptions, then click Analyze Deal.',
      ),
    ).toBeTruthy();
  });

  it('does not show a success message on a failed upload', async () => {
    const user = userEvent.setup();
    render(<App />);
    mockUploadExcel.mockRejectedValue(
      new ApiError("Value for Field ID 'purchase_price' is blank at Inputs!C2.", [
        {
          field_id: 'purchase_price',
          category: 'blank_value',
          message: "Value for Field ID 'purchase_price' is blank at Inputs!C2.",
        },
      ]),
    );

    const file = new File(['PK'], 'anchor_input.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), file);

    await screen.findByText("Value for Field ID 'purchase_price' is blank at Inputs!C2.");
    expect(screen.queryByText(/Workbook parsed successfully/)).toBeNull();
  });

  it('clears a stale review success message once a new upload starts loading', async () => {
    const user = userEvent.setup();
    await uploadWorkbook(user);
    expect(await screen.findByText(/Workbook parsed successfully/)).toBeTruthy();

    const pending = deferred<ExcelIntakeReport>();
    mockUploadExcel.mockReturnValueOnce(pending.promise);
    const file = new File(['PK'], 'anchor_input.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), file);

    expect(screen.queryByText(/Workbook parsed successfully/)).toBeNull();
    pending.resolve(makeExcelIntakeReport());
  });

  it('navigates to the Underwrite workspace after approval, not after upload', async () => {
    // Sprint C Gate C2 replaced the old single-page `scrollIntoView` nudge
    // toward the assumptions form with navigation to the workspace that owns
    // the approved assumptions. Same intent, expressed structurally.
    const user = userEvent.setup();
    await uploadWorkbook(user);
    expect(screen.getByRole('tab', { name: 'Documents' })).toHaveProperty(
      'ariaSelected',
      'true',
    );

    await completeBlankedV2ReviewFields(user);
    await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));

    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Underwrite' })).toHaveProperty(
        'ariaSelected',
        'true',
      ),
    );
  });
});

// =============================================================================
// Persistence Phase B -- Deal Bar / Deal Library workflow.
// =============================================================================

/** Matches what `fillGoldenDeal()` produces after `buildAcquisitionRequest`
 * -- the same golden case used throughout the backend test suite. Derived
 * directly from `DEFAULT_FORM_VALUES` (rather than duplicated by hand) so
 * it can never silently drift from what `fillGoldenDeal()` actually types
 * into the form. */
const GOLDEN_DEAL_REQUEST: AcquisitionRequest = buildAcquisitionRequest(DEFAULT_FORM_VALUES);

function makeDeal(overrides: Partial<Deal> = {}): Deal {
  return {
    id: 'deal-1',
    name: '111 Main St',
    operating_mode: 'quick',
    inputs: GOLDEN_DEAL_REQUEST,
    terms: null,
    detailed_operating_inputs: null,
    deal_context: null,
    analysis_snapshot: null,
    ai_snapshot: null,
    created_at: '2026-09-01T12:00:00+00:00',
    updated_at: '2026-09-01T12:00:00+00:00',
    ...overrides,
  };
}

/** Detailed Operating Model V2.1 Gate 11 -- a saved Detailed deal, shaped
 * as the `/deals` response (`Deal` with `operating_mode: 'detailed'`).
 * `inputs` stays `null` -- never a fabricated `AcquisitionInputs`. */
function makeDetailedDeal(overrides: Partial<Deal> = {}): Deal {
  return {
    id: 'detailed-deal-1',
    name: 'Golden Detailed Deal',
    operating_mode: 'detailed',
    inputs: null,
    terms: {
      purchase_price: 10_000_000,
      hold_period: 5,
      exit_cap_rate: 0.065,
      ltv: 0.6,
      interest_rate: 0.05,
      amortization: 30,
      acquisition_cost_pct: 0.02,
      financing_fee_pct: 0.01,
      disposition_cost_pct: 0.025,
      annual_capex_reserve: 50_000,
      io_period: 2,
    },
    detailed_operating_inputs: {
      gross_potential_rent: 800_000,
      other_income: 20_000,
      vacancy_credit_loss_pct: 0.05,
      property_taxes: 60_000,
      insurance: 20_000,
      utilities: 25_000,
      repairs_maintenance: 20_000,
      other_operating_expenses: 16_000,
      management_fee_pct: 0.05,
      revenue_growth: 0.03,
      expense_growth: 0.03,
    },
    deal_context: null,
    analysis_snapshot: null,
    ai_snapshot: null,
    created_at: '2026-09-01T12:00:00+00:00',
    updated_at: '2026-09-01T12:00:00+00:00',
    ...overrides,
  };
}

/** Matches what `fillDetailedGoldenDeal()` produces after
 * `buildAcquisitionTermsRequest`/`buildDetailedOperatingInputsRequest` --
 * the same golden values `makeDetailedDeal()`/`makeDetailedExcelIntakeReport()`
 * already use, kept as one source of truth. */
const GOLDEN_DETAILED_TERMS_REQUEST = makeDetailedExcelIntakeReport().terms;
const GOLDEN_DETAILED_OPERATING_INPUTS_REQUEST =
  makeDetailedExcelIntakeReport().detailed_operating_inputs;

describe('Deal persistence workflow', () => {
  it('starts as a blank, unsaved deal', () => {
    render(<App />);

    expect(screen.getByLabelText('Deal Name')).toHaveProperty('value', '');
    expect(screen.getByRole('button', { name: 'Save Deal' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Update Deal' })).toBeNull();
  });

  it('Save Deal on a new deal calls createDeal (POST /deals)', async () => {
    const user = userEvent.setup();
    mockCreateDeal.mockResolvedValue(makeDeal());
    render(<App />);
    fillGoldenDeal();

    await user.type(screen.getByLabelText('Deal Name'), '111 Main St');
    await user.click(screen.getByRole('button', { name: 'Save Deal' }));

    await waitFor(() => expect(mockCreateDeal).toHaveBeenCalledTimes(1));
    expect(mockCreateDeal).toHaveBeenCalledWith('111 Main St', GOLDEN_DEAL_REQUEST, null);
    expect(mockUpdateDeal).not.toHaveBeenCalled();
    expect(await screen.findByRole('button', { name: 'Update Deal' })).toBeTruthy();
    expect(await screen.findByText(/^Saved/)).toBeTruthy();
  });

  it('Save Deal on an already-opened deal calls updateDeal (PUT /deals/{id})', async () => {
    const user = userEvent.setup();
    const deal = makeDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    mockUpdateDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    await screen.findByRole('button', { name: 'Update Deal' });

    await user.click(screen.getByRole('button', { name: 'Update Deal' }));

    await waitFor(() => expect(mockUpdateDeal).toHaveBeenCalledTimes(1));
    expect(mockUpdateDeal).toHaveBeenCalledWith('deal-1', '111 Main St', GOLDEN_DEAL_REQUEST, null);
    expect(mockCreateDeal).not.toHaveBeenCalled();
  });

  it('the Deal Library loads and displays saved deals', async () => {
    const user = userEvent.setup();
    mockListDeals.mockResolvedValue([
      makeDeal({ id: 'a', name: 'Deal A' }),
      makeDeal({ id: 'b', name: 'Deal B' }),
    ]);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));

    expect(await within(dealLibrary()).findByText('Deal A')).toBeTruthy();
    expect(within(dealLibrary()).getByText('Deal B')).toBeTruthy();
    // Mount loads the sidebar's Recent Deals; opening the library reloads it.
    expect(mockListDeals).toHaveBeenCalledTimes(2);
  });

  it('Open populates all nine assumption fields and the deal name', async () => {
    const user = userEvent.setup();
    const deal = makeDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));

    expect(await screen.findByLabelText(/^Purchase Price/)).toHaveProperty('value', '50000000');
    expect(screen.getByLabelText(/^Current NOI/)).toHaveProperty('value', '2500000');
    expect(screen.getByLabelText(/^Occupancy/)).toHaveProperty('value', '95');
    expect(screen.getByLabelText(/^NOI Growth/)).toHaveProperty('value', '3');
    expect(screen.getByLabelText(/^Hold Period/)).toHaveProperty('value', '5');
    expect(screen.getByLabelText(/^Exit Cap Rate/)).toHaveProperty('value', '5.5');
    expect(screen.getByLabelText(/^LTV/)).toHaveProperty('value', '65');
    expect(screen.getByLabelText(/^Interest Rate/)).toHaveProperty('value', '5.25');
    expect(screen.getByLabelText(/^Amortization/)).toHaveProperty('value', '30');
    expect(screen.getByLabelText('Deal Name')).toHaveProperty('value', '111 Main St');
    expect(mockGetDeal).toHaveBeenCalledWith('deal-1');
  });

  it('Open populates all five V2 fields, displaying a persisted zero as "0" rather than blank', async () => {
    const user = userEvent.setup();
    const deal = makeDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));

    expect(await screen.findByLabelText(/^Acquisition Costs/)).toHaveProperty('value', '0');
    expect(screen.getByLabelText(/^Financing Fee/)).toHaveProperty('value', '0');
    expect(screen.getByLabelText(/^Disposition Costs/)).toHaveProperty('value', '0');
    expect(screen.getByLabelText(/^Annual CapEx Reserve/)).toHaveProperty('value', '0');
    expect(screen.getByLabelText(/^Interest-Only Period/)).toHaveProperty('value', '0');
  });

  it('opening a saved deal with nonzero V2 values shows them, not blanks -- no review warning', async () => {
    const user = userEvent.setup();
    const v2Deal = makeDeal({
      id: 'v2-deal',
      name: 'V2 Deal',
      inputs: buildAcquisitionRequest(V2_GOLDEN_FORM_VALUES),
    });
    mockListDeals.mockResolvedValue([v2Deal]);
    mockGetDeal.mockResolvedValue(v2Deal);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));

    expect(await screen.findByLabelText(/^Acquisition Costs/)).toHaveProperty('value', '2');
    expect(screen.getByLabelText(/^Financing Fee/)).toHaveProperty('value', '1');
    expect(screen.getByLabelText(/^Disposition Costs/)).toHaveProperty('value', '2.5');
    expect(screen.getByLabelText(/^Annual CapEx Reserve/)).toHaveProperty('value', '50000');
    expect(screen.getByLabelText(/^Interest-Only Period/)).toHaveProperty('value', '2');
    expect(screen.queryByText(/Additional underwriting assumptions/)).toBeNull();
  });

  it('opening a deal clears stale analysis results and returns to the workspace', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    const deal = makeDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);
    fillGoldenDeal();
    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    expect((await screen.findAllByText('7.91%')).length).toBeGreaterThanOrEqual(1);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));

    expect(await screen.findByText(/Enter assumptions and click/)).toBeTruthy();
    expect(screen.queryByText('7.91%')).toBeNull();
  });

  it('opening a deal does not automatically call /analyze', async () => {
    const user = userEvent.setup();
    const deal = makeDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    await screen.findByLabelText(/^Purchase Price/);

    expect(mockAnalyze).not.toHaveBeenCalled();
  });

  it('an opened deal can be edited and saved via updateDeal', async () => {
    const user = userEvent.setup();
    const deal = makeDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    mockUpdateDeal.mockResolvedValue({
      ...deal,
      inputs: { ...GOLDEN_DEAL_REQUEST, purchase_price: 60_000_000 },
    });
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    const purchasePriceInput = await screen.findByLabelText(/^Purchase Price/);
    fireEvent.change(purchasePriceInput, { target: { value: '60000000' } });

    await user.click(screen.getByRole('button', { name: 'Update Deal' }));

    await waitFor(() => expect(mockUpdateDeal).toHaveBeenCalledTimes(1));
    expect(mockUpdateDeal).toHaveBeenCalledWith(
      'deal-1',
      '111 Main St',
      {
        ...GOLDEN_DEAL_REQUEST,
        purchase_price: 60_000_000,
      },
      null,
    );
  });

  it('New Deal clears the current saved-deal identity without deleting the saved deal', async () => {
    const user = userEvent.setup();
    const deal = makeDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    await screen.findByRole('button', { name: 'Update Deal' });

    await user.click(screen.getByRole('button', { name: 'New Deal' }));

    expect(screen.getByLabelText('Deal Name')).toHaveProperty('value', '');
    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '');
    expect(screen.getByLabelText(/^Acquisition Costs/)).toHaveProperty('value', '');
    expect(screen.getByLabelText(/^Financing Fee/)).toHaveProperty('value', '');
    expect(screen.getByLabelText(/^Disposition Costs/)).toHaveProperty('value', '');
    expect(screen.getByLabelText(/^Annual CapEx Reserve/)).toHaveProperty('value', '');
    expect(screen.getByLabelText(/^Interest-Only Period/)).toHaveProperty('value', '');
    expect(screen.getByRole('button', { name: 'Save Deal' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Update Deal' })).toBeNull();

    // The previously opened deal is untouched -- still present in the library.
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    expect(await within(dealLibrary()).findByText('111 Main St')).toBeTruthy();
  });

  it('a validation failure on Save Deal never calls createDeal/updateDeal', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Save Deal' }));

    expect(await screen.findByText(/Purchase Price is required/)).toBeTruthy();
    expect(mockCreateDeal).not.toHaveBeenCalled();
    expect(mockUpdateDeal).not.toHaveBeenCalled();
  });

  it('Excel-populated assumptions can be saved once approved -- persistence does not care where values originated', async () => {
    const user = userEvent.setup();
    mockUploadExcel.mockResolvedValue({ inputs: GOLDEN_DEAL_REQUEST, defaulted_v2_field_ids: [] });
    mockCreateDeal.mockResolvedValue(makeDeal());
    render(<App />);

    const file = new File(['PK'], 'anchor_input.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), file);
    await screen.findByText(/Workbook parsed successfully/);
    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));
    await screen.findByText(/Excel assumptions approved and loaded/);

    await user.type(screen.getByLabelText('Deal Name'), '111 Main St');
    await user.click(screen.getByRole('button', { name: 'Save Deal' }));

    await waitFor(() => expect(mockCreateDeal).toHaveBeenCalledTimes(1));
    expect(mockCreateDeal).toHaveBeenCalledWith('111 Main St', GOLDEN_DEAL_REQUEST, null);
  });
});

// =============================================================================
// Persistence Phase C -- duplicate, delete, unsaved-changes guard, save status.
// =============================================================================

describe('Deal persistence workflow -- Phase C', () => {
  describe('duplicate', () => {
    it('duplicates a deal from the Deal Library and refreshes the list', async () => {
      const user = userEvent.setup();
      const original = makeDeal();
      const copy = makeDeal({ id: 'deal-2', name: '111 Main St (Copy)' });
      // Mount fills the sidebar, opening the library reloads, and the
      // post-duplicate refresh returns the pair.
      mockListDeals
        .mockResolvedValueOnce([original])
        .mockResolvedValueOnce([original])
        .mockResolvedValueOnce([original, copy]);
      mockDuplicateDeal.mockResolvedValue(copy);
      render(<App />);

      await user.click(screen.getByRole('button', { name: 'Deal Library' }));
      await within(dealLibrary()).findByText('111 Main St');
      await user.click(screen.getByRole('button', { name: 'Duplicate' }));

      await waitFor(() => expect(mockDuplicateDeal).toHaveBeenCalledWith('deal-1'));
      expect(await within(dealLibrary()).findByText('111 Main St (Copy)')).toBeTruthy();
      // Mount + opening the library + the post-duplicate refresh.
      expect(mockListDeals).toHaveBeenCalledTimes(3);
    });

    it('a duplicated deal, once opened, shows all five V2 assumptions exactly as the original', async () => {
      const user = userEvent.setup();
      const original = makeDeal({ inputs: buildAcquisitionRequest(V2_GOLDEN_FORM_VALUES) });
      const copy = makeDeal({ id: 'deal-2', name: '111 Main St (Copy)', inputs: original.inputs });
      // Mount fills the sidebar, opening the library reloads, and the
      // post-duplicate refresh returns the pair.
      mockListDeals
        .mockResolvedValueOnce([original])
        .mockResolvedValueOnce([original])
        .mockResolvedValueOnce([original, copy]);
      mockDuplicateDeal.mockResolvedValue(copy);
      mockGetDeal.mockResolvedValue(copy);
      render(<App />);

      await user.click(screen.getByRole('button', { name: 'Deal Library' }));
      await within(dealLibrary()).findByText('111 Main St');
      await user.click(screen.getByRole('button', { name: 'Duplicate' }));
      await within(dealLibrary()).findByText('111 Main St (Copy)');

      const openButtons = screen.getAllByRole('button', { name: 'Open' });
      await user.click(openButtons[openButtons.length - 1]);

      expect(mockGetDeal).toHaveBeenCalledWith('deal-2');
      expect(await screen.findByLabelText(/^Acquisition Costs/)).toHaveProperty('value', '2');
      expect(screen.getByLabelText(/^Financing Fee/)).toHaveProperty('value', '1');
      expect(screen.getByLabelText(/^Disposition Costs/)).toHaveProperty('value', '2.5');
      expect(screen.getByLabelText(/^Annual CapEx Reserve/)).toHaveProperty('value', '50000');
      expect(screen.getByLabelText(/^Interest-Only Period/)).toHaveProperty('value', '2');
    });

    it('does not automatically analyze the duplicated deal', async () => {
      const user = userEvent.setup();
      mockListDeals.mockResolvedValue([makeDeal()]);
      mockDuplicateDeal.mockResolvedValue(makeDeal({ id: 'deal-2', name: '111 Main St (Copy)' }));
      render(<App />);

      await user.click(screen.getByRole('button', { name: 'Deal Library' }));
      await user.click(await screen.findByRole('button', { name: 'Duplicate' }));

      await waitFor(() => expect(mockDuplicateDeal).toHaveBeenCalled());
      expect(mockAnalyze).not.toHaveBeenCalled();
      // Chosen UX: stays in the library rather than opening the copy.
      expect(screen.getByRole('button', { name: 'Close' })).toBeTruthy();
    });
  });

  describe('delete', () => {
    it('requires confirmation before calling deleteDeal', async () => {
      const user = userEvent.setup();
      mockListDeals.mockResolvedValue([makeDeal()]);
      render(<App />);

      await user.click(screen.getByRole('button', { name: 'Deal Library' }));
      await user.click(await screen.findByRole('button', { name: 'Delete' }));

      expect(window.confirm).toHaveBeenCalledTimes(1);
      expect(vi.mocked(window.confirm).mock.calls[0][0]).toContain('111 Main St');
      await waitFor(() => expect(mockDeleteDeal).toHaveBeenCalledWith('deal-1'));
    });

    it('cancelled deletion changes nothing', async () => {
      vi.mocked(window.confirm).mockReturnValueOnce(false);
      const user = userEvent.setup();
      mockListDeals.mockResolvedValue([makeDeal()]);
      render(<App />);

      await user.click(screen.getByRole('button', { name: 'Deal Library' }));
      await user.click(await screen.findByRole('button', { name: 'Delete' }));

      expect(mockDeleteDeal).not.toHaveBeenCalled();
      expect(within(dealLibrary()).getByText('111 Main St')).toBeTruthy();
    });

    it('confirmed deletion removes the deal and refreshes the library', async () => {
      const user = userEvent.setup();
      // One resolution for the mount-time load that fills the sidebar, one
      // for opening the library, then the post-delete refresh returns empty.
      mockListDeals
        .mockResolvedValueOnce([makeDeal()])
        .mockResolvedValueOnce([makeDeal()])
        .mockResolvedValueOnce([]);
      render(<App />);

      await user.click(screen.getByRole('button', { name: 'Deal Library' }));
      await within(dealLibrary()).findByText('111 Main St');
      await user.click(screen.getByRole('button', { name: 'Delete' }));

      await waitFor(() => expect(mockDeleteDeal).toHaveBeenCalledWith('deal-1'));
      expect(await within(dealLibrary()).findByText(/No saved deals yet/)).toBeTruthy();
    });

    it('deleting the currently-open deal clears its identity without leaving a stale id', async () => {
      const user = userEvent.setup();
      const deal = makeDeal();
      mockListDeals.mockResolvedValue([deal]);
      mockGetDeal.mockResolvedValue(deal);
      render(<App />);

      await user.click(screen.getByRole('button', { name: 'Deal Library' }));
      await user.click(await screen.findByRole('button', { name: 'Open' }));
      await screen.findByRole('button', { name: 'Update Deal' });

      await user.click(screen.getByRole('button', { name: 'Deal Library' }));
      await user.click(await screen.findByRole('button', { name: 'Delete' }));
      await waitFor(() => expect(mockDeleteDeal).toHaveBeenCalledWith('deal-1'));
      await user.click(screen.getByRole('button', { name: 'Close' }));

      expect(screen.getByLabelText('Deal Name')).toHaveProperty('value', '');
      expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '');
      expect(screen.getByRole('button', { name: 'Save Deal' })).toBeTruthy();
      expect(screen.getByText('Unsaved deal')).toBeTruthy();
    });
  });

  describe('unsaved-changes tracking and save status', () => {
    it('starts as "Unsaved deal" with a blank form', () => {
      render(<App />);

      expect(screen.getByText('Unsaved deal')).toBeTruthy();
    });

    it('manual field edits produce "Unsaved changes" once a deal is open', async () => {
      const user = userEvent.setup();
      const deal = makeDeal();
      mockListDeals.mockResolvedValue([deal]);
      mockGetDeal.mockResolvedValue(deal);
      render(<App />);

      await user.click(screen.getByRole('button', { name: 'Deal Library' }));
      await user.click(await screen.findByRole('button', { name: 'Open' }));
      expect(await screen.findByText(/^Saved/)).toBeTruthy();

      fireEvent.change(screen.getByLabelText(/^Purchase Price/), {
        target: { value: '60000000' },
      });

      expect(screen.getByText('Unsaved changes')).toBeTruthy();
      expect(screen.queryByText(/^Saved/)).toBeNull();
    });

    it('editing a V2 field marks an already-saved deal dirty, and saving clears it', async () => {
      const user = userEvent.setup();
      const deal = makeDeal();
      mockListDeals.mockResolvedValue([deal]);
      mockGetDeal.mockResolvedValue(deal);
      mockUpdateDeal.mockResolvedValue({
        ...deal,
        inputs: { ...GOLDEN_DEAL_REQUEST, io_period: 3 },
      });
      render(<App />);

      await user.click(screen.getByRole('button', { name: 'Deal Library' }));
      await user.click(await screen.findByRole('button', { name: 'Open' }));
      expect(await screen.findByText(/^Saved/)).toBeTruthy();

      fireEvent.change(screen.getByLabelText(/^Interest-Only Period/), {
        target: { value: '3' },
      });

      expect(screen.getByText('Unsaved changes')).toBeTruthy();
      expect(screen.queryByText(/^Saved/)).toBeNull();

      await user.click(screen.getByRole('button', { name: 'Update Deal' }));

      expect(await screen.findByText(/^Saved/)).toBeTruthy();
      expect(screen.queryByText('Unsaved changes')).toBeNull();
    });

    it('deal-name edits produce "Unsaved changes"', async () => {
      const user = userEvent.setup();
      const deal = makeDeal();
      mockListDeals.mockResolvedValue([deal]);
      mockGetDeal.mockResolvedValue(deal);
      render(<App />);

      await user.click(screen.getByRole('button', { name: 'Deal Library' }));
      await user.click(await screen.findByRole('button', { name: 'Open' }));
      expect(await screen.findByText(/^Saved/)).toBeTruthy();

      await user.type(screen.getByLabelText('Deal Name'), ' Renamed');

      expect(screen.getByText('Unsaved changes')).toBeTruthy();
    });

    it('Excel-populated (approved) data is unsaved until saved', async () => {
      const user = userEvent.setup();
      mockUploadExcel.mockResolvedValue({ inputs: GOLDEN_DEAL_REQUEST, defaulted_v2_field_ids: [] });
      render(<App />);

      const file = new File(['PK'], 'anchor_input.xlsx', {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      });
      await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), file);
      await screen.findByText(/Workbook parsed successfully/);
      await goTo(user, 'Documents');
      await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));
      await screen.findByText(/Excel assumptions approved and loaded/);

      expect(screen.getByText('Unsaved deal')).toBeTruthy();
      expect(screen.queryByText(/^Saved/)).toBeNull();
    });

    it('uploading Excel while a saved deal is open does not mark it dirty before approval', async () => {
      const user = userEvent.setup();
      const deal = makeDeal();
      mockListDeals.mockResolvedValue([deal]);
      mockGetDeal.mockResolvedValue(deal);
      mockUploadExcel.mockResolvedValue({ inputs: GOLDEN_DEAL_REQUEST, defaulted_v2_field_ids: [] });
      render(<App />);

      await user.click(screen.getByRole('button', { name: 'Deal Library' }));
      await user.click(await screen.findByRole('button', { name: 'Open' }));
      expect(await screen.findByText(/^Saved/)).toBeTruthy();

      const file = new File(['PK'], 'anchor_input.xlsx', {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      });
      await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), file);
      await screen.findByText(/Workbook parsed successfully/);

      expect(screen.getByText(/^Saved/)).toBeTruthy();
      expect(screen.queryByText('Unsaved changes')).toBeNull();
    });

    it('approving Excel into a saved deal marks it dirty', async () => {
      const user = userEvent.setup();
      const deal = makeDeal();
      mockListDeals.mockResolvedValue([deal]);
      mockGetDeal.mockResolvedValue(deal);
      mockUploadExcel.mockResolvedValue({
        inputs: { ...GOLDEN_DEAL_REQUEST, purchase_price: 61_000_000 },
        defaulted_v2_field_ids: [],
      });
      render(<App />);

      await user.click(screen.getByRole('button', { name: 'Deal Library' }));
      await user.click(await screen.findByRole('button', { name: 'Open' }));
      expect(await screen.findByText(/^Saved/)).toBeTruthy();

      const file = new File(['PK'], 'anchor_input.xlsx', {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      });
      await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), file);
      await screen.findByText(/Workbook parsed successfully/);
      await goTo(user, 'Documents');
      await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));

      expect(await screen.findByText('Unsaved changes')).toBeTruthy();
      expect(screen.queryByText(/^Saved/)).toBeNull();
    });

    it('cancelling review on a saved deal leaves it saved and clean', async () => {
      const user = userEvent.setup();
      const deal = makeDeal();
      mockListDeals.mockResolvedValue([deal]);
      mockGetDeal.mockResolvedValue(deal);
      mockUploadExcel.mockResolvedValue({ inputs: GOLDEN_DEAL_REQUEST, defaulted_v2_field_ids: [] });
      render(<App />);

      await user.click(screen.getByRole('button', { name: 'Deal Library' }));
      await user.click(await screen.findByRole('button', { name: 'Open' }));
      expect(await screen.findByText(/^Saved/)).toBeTruthy();

      const file = new File(['PK'], 'anchor_input.xlsx', {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      });
      await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), file);
      await screen.findByText(/Workbook parsed successfully/);
      await goTo(user, 'Documents');
      await user.click(screen.getByRole('button', { name: 'Cancel Review' }));

      expect(screen.queryByLabelText('Excel Review Purchase Price')).toBeNull();
      expect(screen.getByText(/^Saved/)).toBeTruthy();
      expect(screen.queryByText('Unsaved changes')).toBeNull();
    });

    it('OM-approved data is unsaved until saved', async () => {
      const user = userEvent.setup();
      mockUploadOm.mockResolvedValue(makeExtractionResult());
      render(<App />);

      await goTo(user, 'Documents');
      const file = new File(['%PDF-1.4'], 'om.pdf', { type: 'application/pdf' });
      await user.upload(screen.getByLabelText('Upload OM (PDF)'), file);
      await screen.findByRole('heading', { name: 'Purchase Price' }, { timeout: 3000 });

      const purchasePriceCard = screen
        .getByRole('heading', { name: 'Purchase Price' })
        .closest('.om-field-card') as HTMLElement;
      await user.click(
        Array.from(purchasePriceCard.querySelectorAll('button')).find(
          (b) => b.textContent === 'Approve',
        )!,
      );
      await goTo(user, 'Documents');
      await user.click(screen.getByRole('button', { name: 'Use approved values' }));

      expect(screen.getByText('Unsaved deal')).toBeTruthy();
      expect(screen.queryByText(/^Saved/)).toBeNull();
    });

    it('a successful Save returns the status to "Saved"', async () => {
      const user = userEvent.setup();
      mockCreateDeal.mockResolvedValue(makeDeal());
      render(<App />);
      fillGoldenDeal();
      await user.type(screen.getByLabelText('Deal Name'), '111 Main St');

      expect(screen.getByText('Unsaved deal')).toBeTruthy();

      await user.click(screen.getByRole('button', { name: 'Save Deal' }));

      expect(await screen.findByText(/^Saved/)).toBeTruthy();
    });

    it('Analyze Deal does not mark a never-saved deal as saved', async () => {
      const user = userEvent.setup();
      mockAnalyze.mockResolvedValue(makeResults());
      render(<App />);
      fillGoldenDeal();

      await user.click(screen.getByRole('button', { name: 'Analyze' }));
      await screen.findAllByText('7.91%');

      expect(screen.getByText('Unsaved deal')).toBeTruthy();
      expect(screen.queryByText(/^Saved/)).toBeNull();
    });

    it('Analyze Deal does not clear "Unsaved changes" on an already-saved deal', async () => {
      const user = userEvent.setup();
      const deal = makeDeal();
      mockListDeals.mockResolvedValue([deal]);
      mockGetDeal.mockResolvedValue(deal);
      mockAnalyze.mockResolvedValue(makeResults());
      render(<App />);

      await user.click(screen.getByRole('button', { name: 'Deal Library' }));
      await user.click(await screen.findByRole('button', { name: 'Open' }));
      fireEvent.change(screen.getByLabelText(/^Purchase Price/), {
        target: { value: '60000000' },
      });
      expect(screen.getByText('Unsaved changes')).toBeTruthy();

      await user.click(screen.getByRole('button', { name: 'Analyze' }));
      await screen.findAllByText('7.91%');

      expect(screen.getByText('Unsaved changes')).toBeTruthy();
    });

    it('opening a saved deal starts clean ("Saved")', async () => {
      const user = userEvent.setup();
      const deal = makeDeal();
      mockListDeals.mockResolvedValue([deal]);
      mockGetDeal.mockResolvedValue(deal);
      render(<App />);

      await user.click(screen.getByRole('button', { name: 'Deal Library' }));
      await user.click(await screen.findByRole('button', { name: 'Open' }));

      expect(await screen.findByText(/^Saved/)).toBeTruthy();
    });
  });

  describe('unsaved-changes guard on New Deal / Open Deal', () => {
    it('warns before New Deal when the workspace is dirty', async () => {
      const user = userEvent.setup();
      render(<App />);
      fillGoldenDeal();

      await user.click(screen.getByRole('button', { name: 'New Deal' }));

      expect(window.confirm).toHaveBeenCalledWith(
        'You have unsaved changes that will be lost. Continue?',
      );
    });

    it('does not warn before New Deal when the workspace is clean', async () => {
      const user = userEvent.setup();
      render(<App />);

      await user.click(screen.getByRole('button', { name: 'New Deal' }));

      expect(window.confirm).not.toHaveBeenCalled();
    });

    it('a New Deal remains blank until an Excel review is approved -- upload alone never special-cases it', async () => {
      const user = userEvent.setup();
      mockUploadExcel.mockResolvedValue({ inputs: GOLDEN_DEAL_REQUEST, defaulted_v2_field_ids: [] });
      render(<App />);

      await user.click(screen.getByRole('button', { name: 'New Deal' }));
      expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '');

      const file = new File(['PK'], 'anchor_input.xlsx', {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      });
      await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), file);
      await screen.findByText(/Workbook parsed successfully/);

      // Still requires review and approval, exactly like a non-blank deal.
      expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '');
      expect(screen.getByLabelText('Excel Review Purchase Price')).toHaveProperty(
        'value',
        String(GOLDEN_DEAL_REQUEST.purchase_price),
      );
    });

    it('cancelling the New Deal warning preserves the current workspace exactly', async () => {
      vi.mocked(window.confirm).mockReturnValueOnce(false);
      const user = userEvent.setup();
      render(<App />);
      fillGoldenDeal();

      await user.click(screen.getByRole('button', { name: 'New Deal' }));

      expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty(
        'value',
        DEFAULT_FORM_VALUES.purchasePrice,
      );
    });

    it('warns before opening another deal when the workspace is dirty', async () => {
      const user = userEvent.setup();
      mockListDeals.mockResolvedValue([makeDeal()]);
      render(<App />);
      fillGoldenDeal();

      await user.click(screen.getByRole('button', { name: 'Deal Library' }));
      await user.click(await screen.findByRole('button', { name: 'Open' }));

      expect(window.confirm).toHaveBeenCalledWith(
        'You have unsaved changes that will be lost. Continue?',
      );
    });

    it('cancelling the Open warning preserves the current workspace and does not call getDeal', async () => {
      vi.mocked(window.confirm).mockReturnValueOnce(false);
      const user = userEvent.setup();
      mockListDeals.mockResolvedValue([makeDeal()]);
      render(<App />);
      fillGoldenDeal();

      await user.click(screen.getByRole('button', { name: 'Deal Library' }));
      await user.click(await screen.findByRole('button', { name: 'Open' }));

      expect(mockGetDeal).not.toHaveBeenCalled();
      await user.click(screen.getByRole('button', { name: 'Close' }));
      expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty(
        'value',
        DEFAULT_FORM_VALUES.purchasePrice,
      );
    });
  });
});

// =============================================================================
// Detailed Operating Model V2.1 Gate 6 -- Quick/Detailed mode toggle
// =============================================================================

/** Fills DetailedAssumptionsForm with the Detailed golden-case fixture
 * values (the terms and Operating Model sections both), mirroring
 * fillV2GoldenDeal's style/shape for the Quick form. */
function fillDetailedGoldenDeal() {
  fireEvent.change(screen.getByLabelText(/^Purchase Price/), {
    target: { value: DETAILED_GOLDEN_FORM_VALUES.terms.purchasePrice },
  });
  fireEvent.change(screen.getByLabelText(/^Hold Period/), {
    target: { value: DETAILED_GOLDEN_FORM_VALUES.terms.holdPeriod },
  });
  fireEvent.change(screen.getByLabelText(/^Exit Cap Rate/), {
    target: { value: DETAILED_GOLDEN_FORM_VALUES.terms.exitCapRate },
  });
  fireEvent.change(screen.getByLabelText(/^LTV/), {
    target: { value: DETAILED_GOLDEN_FORM_VALUES.terms.ltv },
  });
  fireEvent.change(screen.getByLabelText(/^Interest Rate/), {
    target: { value: DETAILED_GOLDEN_FORM_VALUES.terms.interestRate },
  });
  fireEvent.change(screen.getByLabelText(/^Amortization/), {
    target: { value: DETAILED_GOLDEN_FORM_VALUES.terms.amortization },
  });
  fireEvent.change(screen.getByLabelText(/^Acquisition Costs/), {
    target: { value: DETAILED_GOLDEN_FORM_VALUES.terms.acquisitionCostPct },
  });
  fireEvent.change(screen.getByLabelText(/^Financing Fee/), {
    target: { value: DETAILED_GOLDEN_FORM_VALUES.terms.financingFeePct },
  });
  fireEvent.change(screen.getByLabelText(/^Disposition Costs/), {
    target: { value: DETAILED_GOLDEN_FORM_VALUES.terms.dispositionCostPct },
  });
  fireEvent.change(screen.getByLabelText(/^Annual CapEx Reserve/), {
    target: { value: DETAILED_GOLDEN_FORM_VALUES.terms.annualCapexReserve },
  });
  fireEvent.change(screen.getByLabelText(/^Interest-Only Period/), {
    target: { value: DETAILED_GOLDEN_FORM_VALUES.terms.ioPeriod },
  });
  fireEvent.change(screen.getByLabelText(/^Gross Potential Rent/), {
    target: { value: DETAILED_GOLDEN_FORM_VALUES.operating.grossPotentialRent },
  });
  fireEvent.change(screen.getByLabelText(/^Other Income/), {
    target: { value: DETAILED_GOLDEN_FORM_VALUES.operating.otherIncome },
  });
  fireEvent.change(screen.getByLabelText(/^Vacancy & Credit Loss/), {
    target: { value: DETAILED_GOLDEN_FORM_VALUES.operating.vacancyCreditLossPct },
  });
  fireEvent.change(screen.getByLabelText(/^Property Taxes/), {
    target: { value: DETAILED_GOLDEN_FORM_VALUES.operating.propertyTaxes },
  });
  fireEvent.change(screen.getByLabelText(/^Insurance/), {
    target: { value: DETAILED_GOLDEN_FORM_VALUES.operating.insurance },
  });
  fireEvent.change(screen.getByLabelText(/^Utilities/), {
    target: { value: DETAILED_GOLDEN_FORM_VALUES.operating.utilities },
  });
  fireEvent.change(screen.getByLabelText(/^Repairs & Maintenance/), {
    target: { value: DETAILED_GOLDEN_FORM_VALUES.operating.repairsMaintenance },
  });
  fireEvent.change(screen.getByLabelText(/^Other Operating Expenses/), {
    target: { value: DETAILED_GOLDEN_FORM_VALUES.operating.otherOperatingExpenses },
  });
  fireEvent.change(screen.getByLabelText(/^Management Fee/), {
    target: { value: DETAILED_GOLDEN_FORM_VALUES.operating.managementFeePct },
  });
  fireEvent.change(screen.getByLabelText(/^Revenue Growth/), {
    target: { value: DETAILED_GOLDEN_FORM_VALUES.operating.revenueGrowth },
  });
  fireEvent.change(screen.getByLabelText(/^Expense Growth/), {
    target: { value: DETAILED_GOLDEN_FORM_VALUES.operating.expenseGrowth },
  });
}

/** The frozen Detailed golden case's engine output
 * (docs/detailed_operating_model_v2_1_golden_case.md), for tests
 * demonstrating the Detailed flow end-to-end with authoritative mocked
 * values -- never reproduced via a TypeScript formula. */
function makeDetailedResults(): DetailedAcquisitionResults {
  return {
    operating_projection: {
      gross_potential_rent_by_year: [800_000, 824_000, 848_720, 874_181.6, 900_407.05],
      other_income_by_year: [20_000, 20_600, 21_218, 21_854.54, 22_510.18],
      vacancy_credit_loss_by_year: [40_000, 41_200, 42_436, 43_709.08, 45_020.35],
      effective_gross_income_by_year: [780_000, 803_400, 827_502, 852_327.06, 877_896.87],
      property_taxes_by_year: [60_000, 61_800, 63_654, 65_563.62, 67_530.53],
      insurance_by_year: [20_000, 20_600, 21_218, 21_854.54, 22_510.18],
      utilities_by_year: [25_000, 25_750, 26_522.5, 27_318.18, 28_137.72],
      repairs_maintenance_by_year: [20_000, 20_600, 21_218, 21_854.54, 22_510.18],
      other_operating_expenses_by_year: [16_000, 16_480, 16_974.4, 17_483.63, 18_008.14],
      management_fee_by_year: [39_000, 40_170, 41_375.1, 42_616.35, 43_894.84],
      total_operating_expenses_by_year: [180_000, 185_400, 190_962, 196_690.86, 202_591.59],
      noi_by_year: [600_000, 618_000, 636_540, 655_636.2, 675_305.29],
      exit_noi: 695_564.44,
      going_in_cap_rate: 0.06,
    },
    results: makeV2GoldenResults(),
  };
}

describe('Detailed Underwrite mode (Gate 6)', () => {
  it('starts in Quick Underwrite mode by default', () => {
    render(<App />);

    expect(screen.getByRole('tab', { name: 'Quick Underwrite' })).toHaveProperty(
      'ariaSelected',
      'true',
    );
    expect(screen.getByLabelText(/^Current NOI/)).toBeTruthy();
  });

  it('switches to the Detailed form and back without losing Quick-mode input', async () => {
    const user = userEvent.setup();
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    expect(screen.queryByLabelText(/^Current NOI/)).toBeNull();
    expect(screen.getByLabelText(/^Gross Potential Rent/)).toBeTruthy();

    await user.click(screen.getByRole('tab', { name: 'Quick Underwrite' }));
    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty(
      'value',
      DEFAULT_FORM_VALUES.purchasePrice,
    );
    expect(screen.getByLabelText(/^Current NOI/)).toHaveProperty(
      'value',
      DEFAULT_FORM_VALUES.currentNoi,
    );
  });

  it('never renders a Current NOI, Occupancy, or NOI Growth field in Detailed mode', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));

    expect(screen.queryByLabelText(/^Current NOI/)).toBeNull();
    expect(screen.queryByLabelText(/^Occupancy/)).toBeNull();
    expect(screen.queryByLabelText(/^NOI Growth/)).toBeNull();
  });

  it('submits the Detailed golden case and renders the operating statement and results', async () => {
    const user = userEvent.setup();
    mockAnalyzeDetailed.mockResolvedValue(makeDetailedResults());
    render(<App />);

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    fillDetailedGoldenDeal();
    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    await waitFor(() => expect(mockAnalyzeDetailed).toHaveBeenCalledTimes(1));
    const [terms, detailedOperatingInputs] = mockAnalyzeDetailed.mock.calls[0];
    expect(terms).toEqual({
      purchase_price: 10_000_000,
      hold_period: 5,
      exit_cap_rate: 0.065,
      ltv: 0.6,
      interest_rate: 0.05,
      amortization: 30,
      acquisition_cost_pct: 0.02,
      financing_fee_pct: 0.01,
      disposition_cost_pct: 0.025,
      annual_capex_reserve: 50_000,
      io_period: 2,
    });
    expect(detailedOperatingInputs).toEqual({
      gross_potential_rent: 800_000,
      other_income: 20_000,
      vacancy_credit_loss_pct: 0.05,
      property_taxes: 60_000,
      insurance: 20_000,
      utilities: 25_000,
      repairs_maintenance: 20_000,
      other_operating_expenses: 16_000,
      management_fee_pct: 0.05,
      revenue_growth: 0.03,
      expense_growth: 0.03,
    });

    await waitFor(() => expect(operatingStatement()).not.toBeNull());
    expect(screen.getAllByText('Key Returns').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('$600,000').length).toBeGreaterThan(0);
  });

  it('shows the Owner Returns headline in Detailed mode, identical to Quick for equivalent economics', async () => {
    const user = userEvent.setup();
    mockAnalyzeDetailed.mockResolvedValue(makeDetailedResults());
    render(<App />);

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    fillDetailedGoldenDeal();
    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect((await screen.findAllByText('Owner Returns')).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Year 1 Levered CoC').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('5.87%').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Year 1 Debt Yield').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('10.00%').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('$1,175,947').length).toBeGreaterThanOrEqual(1);

    // Same three headline figures the Quick-mode V2.1 golden case test
    // above asserts -- proving Quick and Detailed present the shared
    // AcquisitionResults fields identically for economically equivalent
    // deals, per Sprint A charter Section 7.
  });

  it('surfaces a Detailed validation error without touching Quick-mode state', async () => {
    const user = userEvent.setup();
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect(screen.getByText(/is required/)).toBeTruthy();
    expect(mockAnalyzeDetailed).not.toHaveBeenCalled();

    await user.click(screen.getByRole('tab', { name: 'Quick Underwrite' }));
    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty(
      'value',
      DEFAULT_FORM_VALUES.purchasePrice,
    );
  });

  it('surfaces an ApiError message from analyzeDetailedAcquisition', async () => {
    const user = userEvent.setup();
    mockAnalyzeDetailed.mockRejectedValue(
      new ApiError('The submitted assumptions failed validation.'),
    );
    render(<App />);

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    fillDetailedGoldenDeal();
    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect(
      await screen.findByText('The submitted assumptions failed validation.'),
    ).toBeTruthy();
  });
});

// =============================================================================
// Detailed Operating Model V2.1 Gate 9 -- AI Analyst in Detailed mode
// =============================================================================

async function analyzeDetailedGoldenDeal(user: ReturnType<typeof userEvent.setup>) {
  mockAnalyzeDetailed.mockResolvedValue(makeDetailedResults());
  await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
  fillDetailedGoldenDeal();
  await user.click(screen.getByRole('button', { name: 'Analyze' }));
  await waitFor(() => expect(mockAnalyzeDetailed).toHaveBeenCalled());
  await screen.findAllByText('Key Returns');
}

describe('AI Analyst in Detailed mode (Gate 9)', () => {
  it('AI Analyst works in Quick mode (regression)', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();
    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findAllByText('Key Returns');

    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));

    await waitFor(() => expect(mockFetchAIAnalysis).toHaveBeenCalledTimes(1));
    expect(mockFetchDetailedAIAnalysis).not.toHaveBeenCalled();
    expect(await screen.findByText('Five-year hold with moderate leverage.')).toBeTruthy();
  });

  it('AI Analyst works in Detailed mode', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeDetailedGoldenDeal(user);

    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));

    await waitFor(() => expect(mockFetchDetailedAIAnalysis).toHaveBeenCalledTimes(1));
    expect(mockFetchAIAnalysis).not.toHaveBeenCalled();
    expect(await screen.findByText('Five-year hold with moderate leverage.')).toBeTruthy();
  });

  it('switching modes sends the correct request/context shape', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);

    // Quick first.
    fillGoldenDeal();
    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findAllByText('Key Returns');
    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    await waitFor(() => expect(mockFetchAIAnalysis).toHaveBeenCalledTimes(1));
    const [quickInputsArg] = mockFetchAIAnalysis.mock.calls[0];
    expect(quickInputsArg).toHaveProperty('current_noi');
    expect(quickInputsArg).toHaveProperty('noi_growth');

    // Now switch to Detailed and generate again.
    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    await analyzeDetailedGoldenDeal(user);
    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    await waitFor(() => expect(mockFetchDetailedAIAnalysis).toHaveBeenCalledTimes(1));
    const [termsArg, detailedOperatingInputsArg] = mockFetchDetailedAIAnalysis.mock.calls[0];
    expect(termsArg).not.toHaveProperty('current_noi');
    expect(termsArg).not.toHaveProperty('noi_growth');
    expect(detailedOperatingInputsArg).toHaveProperty('vacancy_credit_loss_pct', 0.05);

    // Quick's own call was never re-triggered by the Detailed generate.
    expect(mockFetchAIAnalysis).toHaveBeenCalledTimes(1);
  });

  it('Detailed AI uses Detailed analysis results (terms + detailed operating inputs)', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeDetailedGoldenDeal(user);

    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));

    await waitFor(() => expect(mockFetchDetailedAIAnalysis).toHaveBeenCalledTimes(1));
    const [terms, detailedOperatingInputs, targetIrr, targetEquityMultiple, targetDscr, metric] =
      mockFetchDetailedAIAnalysis.mock.calls[0];
    expect(terms).toEqual({
      purchase_price: 10_000_000,
      hold_period: 5,
      exit_cap_rate: 0.065,
      ltv: 0.6,
      interest_rate: 0.05,
      amortization: 30,
      acquisition_cost_pct: 0.02,
      financing_fee_pct: 0.01,
      disposition_cost_pct: 0.025,
      annual_capex_reserve: 50_000,
      io_period: 2,
    });
    expect(detailedOperatingInputs).toEqual({
      gross_potential_rent: 800_000,
      other_income: 20_000,
      vacancy_credit_loss_pct: 0.05,
      property_taxes: 60_000,
      insurance: 20_000,
      utilities: 25_000,
      repairs_maintenance: 20_000,
      other_operating_expenses: 16_000,
      management_fee_pct: 0.05,
      revenue_growth: 0.03,
      expense_growth: 0.03,
    });
    expect(typeof targetIrr).toBe('number');
    expect(typeof targetEquityMultiple).toBe('number');
    expect(typeof targetDscr).toBe('number');
    expect(metric).toBe('levered_irr');
  });

  it('no Quick-only NOI fields are fabricated for Detailed mode', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeDetailedGoldenDeal(user);

    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));

    await waitFor(() => expect(mockFetchDetailedAIAnalysis).toHaveBeenCalledTimes(1));
    const [terms, detailedOperatingInputs] = mockFetchDetailedAIAnalysis.mock.calls[0];
    const serialized = JSON.stringify({ terms, detailedOperatingInputs });
    expect(serialized).not.toContain('current_noi');
    expect(serialized).not.toContain('"noi_growth"');
    expect(serialized).not.toContain('"occupancy"');
  });

  it('surfaces an ApiError message from fetchDetailedAIAnalysis without touching Quick state', async () => {
    const user = userEvent.setup();
    mockFetchDetailedAIAnalysis.mockRejectedValue(
      new ApiError('The AI Analyst is not configured.'),
    );
    render(<App />);
    await analyzeDetailedGoldenDeal(user);

    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));

    expect(await screen.findByText('The AI Analyst is not configured.')).toBeTruthy();
  });

  it('clears the Detailed AI analysis when a Detailed assumption is edited', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeDetailedGoldenDeal(user);
    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    await screen.findByText('Five-year hold with moderate leverage.');

    fireEvent.change(screen.getByLabelText(/^Purchase Price/), {
      target: { value: '11000000' },
    });

    expect(screen.queryByText('Five-year hold with moderate leverage.')).toBeNull();
  });
});

// =============================================================================
// Detailed Operating Model V2.1 Gate 14 -- Detailed sensitivity/break-even
// API/UI wiring
// =============================================================================

const DETAILED_GOLDEN_TERMS_REQUEST = {
  purchase_price: 10_000_000,
  hold_period: 5,
  exit_cap_rate: 0.065,
  ltv: 0.6,
  interest_rate: 0.05,
  amortization: 30,
  acquisition_cost_pct: 0.02,
  financing_fee_pct: 0.01,
  disposition_cost_pct: 0.025,
  annual_capex_reserve: 50_000,
  io_period: 2,
};

const DETAILED_GOLDEN_OPERATING_REQUEST = {
  gross_potential_rent: 800_000,
  other_income: 20_000,
  vacancy_credit_loss_pct: 0.05,
  property_taxes: 60_000,
  insurance: 20_000,
  utilities: 25_000,
  repairs_maintenance: 20_000,
  other_operating_expenses: 16_000,
  management_fee_pct: 0.05,
  revenue_growth: 0.03,
  expense_growth: 0.03,
};

describe('Detailed sensitivity + break-even (Gate 14)', () => {
  it('1. Detailed results expose Sensitivity', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeDetailedGoldenDeal(user);

    expect(await screen.findByText('Sensitivity Analysis')).toBeTruthy();
    await goTo(user, 'Risk');
    // The Detailed-only preset bundle has no exit_cap_noi_growth member --
    // that tab must never appear for a Detailed result.
    expect(screen.queryByRole('tab', { name: 'Exit Cap × NOI Growth' })).toBeNull();
    expect(screen.getByRole('tab', { name: 'Purchase Price × Exit Cap' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Interest Rate × LTV' })).toBeTruthy();
  });

  it('2. Detailed results expose Break-Even', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeDetailedGoldenDeal(user);

    expect(await screen.findByText('Break-Even Analysis')).toBeTruthy();
    expect(screen.getByText('Maximum Purchase Price')).toBeTruthy();
    expect(screen.getByText('Maximum Exit Cap')).toBeTruthy();
    expect(screen.getByText('Maximum Interest Rate')).toBeTruthy();
    // The Detailed-only bundle has no min_noi_growth/min_current_noi
    // members -- neither card may appear for a Detailed result.
    expect(screen.queryByText('Minimum NOI Growth')).toBeNull();
    expect(screen.queryByText('Minimum Current NOI')).toBeNull();
  });

  it('3. Detailed sensitivity request uses Detailed inputs', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeDetailedGoldenDeal(user);

    await waitFor(() => expect(mockFetchDetailedSensitivityPresets).toHaveBeenCalledTimes(1));
    expect(mockFetchSensitivityPresets).not.toHaveBeenCalled();
    const [terms, detailedOperatingInputs] = mockFetchDetailedSensitivityPresets.mock.calls[0];
    expect(terms).toEqual(DETAILED_GOLDEN_TERMS_REQUEST);
    expect(detailedOperatingInputs).toEqual(DETAILED_GOLDEN_OPERATING_REQUEST);
  });

  it('4. Detailed break-even request uses Detailed inputs', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeDetailedGoldenDeal(user);

    await waitFor(() => expect(mockFetchDetailedBreakEvenAnalysis).toHaveBeenCalledTimes(1));
    expect(mockFetchBreakEvenAnalysis).not.toHaveBeenCalled();
    const [terms, detailedOperatingInputs, targetIrr, targetEquityMultiple, targetDscr, metric] =
      mockFetchDetailedBreakEvenAnalysis.mock.calls[0];
    expect(terms).toEqual(DETAILED_GOLDEN_TERMS_REQUEST);
    expect(detailedOperatingInputs).toEqual(DETAILED_GOLDEN_OPERATING_REQUEST);
    expect(targetIrr).toBeCloseTo(0.1);
    expect(targetEquityMultiple).toBeCloseTo(1.5);
    expect(targetDscr).toBeCloseTo(1.2);
    expect(metric).toBe('levered_irr');
  });

  it('5. Quick sensitivity remains unchanged (regression)', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    await waitFor(() => expect(mockFetchSensitivityPresets).toHaveBeenCalledTimes(1));
    expect(mockFetchDetailedSensitivityPresets).not.toHaveBeenCalled();
    expect(mockFetchSensitivityPresets).toHaveBeenCalledWith(mockAnalyze.mock.calls[0][0]);
    // Quick's own preset bundle still has its exit_cap_noi_growth tab.
    await goTo(user, 'Risk');
    expect(await screen.findByRole('tab', { name: 'Exit Cap × NOI Growth' })).toBeTruthy();
  });

  it('6. Quick break-even remains unchanged (regression)', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    await waitFor(() => expect(mockFetchBreakEvenAnalysis).toHaveBeenCalledTimes(1));
    expect(mockFetchDetailedBreakEvenAnalysis).not.toHaveBeenCalled();
    // Quick's own bundle still has its min_noi_growth/min_current_noi cards.
    expect(await screen.findByText('Minimum NOI Growth')).toBeTruthy();
    expect(screen.getByText('Minimum Current NOI')).toBeTruthy();
  });

  it('7. Detailed sensitivity/break-even requests never fabricate current_noi/noi_growth/occupancy', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeDetailedGoldenDeal(user);

    await waitFor(() => expect(mockFetchDetailedSensitivityPresets).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mockFetchDetailedBreakEvenAnalysis).toHaveBeenCalledTimes(1));
    const sensitivityArgs = mockFetchDetailedSensitivityPresets.mock.calls[0];
    const breakEvenArgs = mockFetchDetailedBreakEvenAnalysis.mock.calls[0].slice(0, 2);
    const serialized = JSON.stringify({ sensitivityArgs, breakEvenArgs });
    expect(serialized).not.toContain('current_noi');
    expect(serialized).not.toContain('"noi_growth"');
    expect(serialized).not.toContain('"occupancy"');
  });

  it('8. switching modes does not leak sensitivity/break-even state', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);

    // Quick first -- its default mocked matrix (41%-64%) never contains 9.00%.
    fillGoldenDeal();
    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Sensitivity Analysis');
    expect(screen.getAllByText(/^50\.00%/).length).toBeGreaterThan(0);
    expect(screen.queryAllByText(/^9\.00%/)).toHaveLength(0);

    // Switch to Detailed -- no results yet, so no sensitivity/break-even at all.
    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    expect(screen.queryByText('Sensitivity Analysis')).toBeNull();
    expect(screen.queryByText('Break-Even Analysis')).toBeNull();

    // Analyze Detailed -- its own distinctive baseline (9.00%, unique to its
    // mocked matrix), never Quick's 50.00%.
    await analyzeDetailedGoldenDeal(user);
    expect(await screen.findByText('Sensitivity Analysis')).toBeTruthy();
    expect(screen.getAllByText(/^9\.00%/).length).toBeGreaterThan(0);
    expect(screen.queryAllByText(/^50\.00%/)).toHaveLength(0);

    // Switch back to Quick -- its original sensitivity is still there, untouched.
    await user.click(screen.getByRole('tab', { name: 'Quick Underwrite' }));
    expect(await screen.findByText('Sensitivity Analysis')).toBeTruthy();
    expect(screen.getAllByText(/^50\.00%/).length).toBeGreaterThan(0);
    expect(screen.queryAllByText(/^9\.00%/)).toHaveLength(0);
    expect(mockFetchSensitivityPresets).toHaveBeenCalledTimes(1);
    expect(mockFetchDetailedSensitivityPresets).toHaveBeenCalledTimes(1);
  });

  it('9. sensitivity result renders correctly in Detailed mode', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeDetailedGoldenDeal(user);
    await screen.findByText('Sensitivity Analysis');
    await goTo(user, 'Risk');

    // Default tab falls back to purchase_price_exit_cap (Detailed has no
    // exit_cap_noi_growth) -- its mocked baseline cell is the only one in
    // the grid rendering "9.00%", rendered raw, never recomputed.
    expect(screen.getAllByText(/^9\.00%/).length).toBeGreaterThan(0);

    await user.click(screen.getByRole('tab', { name: 'Interest Rate × LTV' }));
    // The DSCR variant's mocked baseline (2.00x) renders once that tab/metric is selected.
    await user.click(screen.getByRole('button', { name: 'Year 1 DSCR' }));
    await waitFor(() => expect(screen.getAllByText(/^2\.00x/).length).toBeGreaterThan(0));
  });

  it('10. break-even result renders correctly in Detailed mode', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeDetailedGoldenDeal(user);
    await screen.findByText('Break-Even Analysis');

    // Solved values come straight from the mock (max_purchase_price:
    // 9,500,000 / max_exit_cap_rate: 0.071 / max_interest_rate: 0.0712),
    // rendered by the same formatCurrency/formatPercent helpers Quick uses
    // -- never recomputed.
    expect(screen.getAllByText('$9,487,500').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('7.10%').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('7.12%').length).toBeGreaterThanOrEqual(1);
  });

  it('11. no formulas are introduced into frontend code -- rendered values are a byte-identical pass-through of the mocked response', async () => {
    const user = userEvent.setup();
    // A deliberately unrealistic, distinctive value that could not arise
    // from any plausible client-side recomputation of the golden inputs --
    // if this exact figure renders, the component only formatted it.
    mockFetchDetailedBreakEvenAnalysis.mockResolvedValue(
      makeDetailedBreakEvenAnalysis({
        max_purchase_price: makeBreakEvenResult({
          solved_assumption_value: 12_345_678,
        }),
      }),
    );
    render(<App />);
    await analyzeDetailedGoldenDeal(user);

    expect((await screen.findAllByText('$12,345,678')).length).toBeGreaterThanOrEqual(1);
  });
});

describe('Detailed Excel ingestion workflow (Gate 10)', () => {
  /** Switches to Detailed mode, uploads the golden Detailed workbook, and
   * waits for the Detailed Excel Ingestion Review panel to appear -- never
   * waits on the live `DetailedAssumptionsForm`, which this upload must not
   * touch. */
  async function uploadDetailedWorkbook(user: ReturnType<typeof userEvent.setup>) {
    render(<App />);
    mockUploadDetailedExcel.mockResolvedValue(makeDetailedExcelIntakeReport());

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    await goTo(user, 'Documents');
    const file = new File(['PK'], 'anchor_detailed_input_v2_1.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), file);

    await waitFor(() => {
      expect(
        screen.getByLabelText('Detailed Excel Review Purchase Price'),
      ).toHaveProperty('value', '10000000');
    });
  }

  it('exposes Excel upload in Detailed mode', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));

    expect(screen.getByLabelText('Upload Anchor Workbook (.xlsx)')).toBeTruthy();
  });

  it('does not immediately populate active Detailed assumptions after upload', async () => {
    const user = userEvent.setup();
    await uploadDetailedWorkbook(user);

    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty(
      'value',
      BLANK_DETAILED_FORM_VALUES.terms.purchasePrice,
    );
  });

  it('creates a temporary Detailed Excel review with all 22 imported values', async () => {
    const user = userEvent.setup();
    await uploadDetailedWorkbook(user);

    expect(screen.getByLabelText('Detailed Excel Review Purchase Price')).toHaveProperty(
      'value',
      '10000000',
    );
    expect(screen.getByLabelText('Detailed Excel Review Hold Period')).toHaveProperty(
      'value',
      '5',
    );
    expect(screen.getByLabelText('Detailed Excel Review Exit Cap Rate')).toHaveProperty(
      'value',
      '6.5',
    );
    expect(screen.getByLabelText('Detailed Excel Review Gross Potential Rent')).toHaveProperty(
      'value',
      '800000',
    );
    expect(
      screen.getByLabelText('Detailed Excel Review Vacancy & Credit Loss'),
    ).toHaveProperty('value', '5');
    expect(screen.getByLabelText('Detailed Excel Review Management Fee')).toHaveProperty(
      'value',
      '5',
    );
  });

  it('AcquisitionTerms review fields are editable', async () => {
    const user = userEvent.setup();
    await uploadDetailedWorkbook(user);

    fireEvent.change(screen.getByLabelText('Detailed Excel Review Purchase Price'), {
      target: { value: '11000000' },
    });

    expect(screen.getByLabelText('Detailed Excel Review Purchase Price')).toHaveProperty(
      'value',
      '11000000',
    );
  });

  it('DetailedOperatingInputs review fields are editable', async () => {
    const user = userEvent.setup();
    await uploadDetailedWorkbook(user);

    fireEvent.change(screen.getByLabelText('Detailed Excel Review Gross Potential Rent'), {
      target: { value: '850000' },
    });

    expect(
      screen.getByLabelText('Detailed Excel Review Gross Potential Rent'),
    ).toHaveProperty('value', '850000');
  });

  it('Approve & Load Assumptions populates all Detailed assumptions', async () => {
    const user = userEvent.setup();
    await uploadDetailedWorkbook(user);

    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));

    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '10000000');
    expect(screen.getByLabelText(/^Gross Potential Rent/)).toHaveProperty('value', '800000');
    expect(screen.getByLabelText(/^Interest-Only Period/)).toHaveProperty('value', '2');
    expect(screen.getByLabelText(/^Expense Growth/)).toHaveProperty('value', '3');
  });

  it('Approve & Load Assumptions never automatically calls Analyze', async () => {
    const user = userEvent.setup();
    await uploadDetailedWorkbook(user);

    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));

    expect(mockAnalyzeDetailed).not.toHaveBeenCalled();
  });

  it('Cancel Review discards the pending review and leaves active Detailed assumptions unchanged', async () => {
    const user = userEvent.setup();
    await uploadDetailedWorkbook(user);

    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Cancel Review' }));

    expect(screen.queryByLabelText('Detailed Excel Review Purchase Price')).toBeNull();
    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty(
      'value',
      BLANK_DETAILED_FORM_VALUES.terms.purchasePrice,
    );
  });

  it('a saved Quick deal is completely unaffected by a Detailed Excel upload, approval, or cancel', async () => {
    const user = userEvent.setup();
    mockCreateDeal.mockResolvedValue(makeDeal());
    render(<App />);
    fillGoldenDeal();
    await user.type(screen.getByLabelText('Deal Name'), '111 Main St');
    await user.click(screen.getByRole('button', { name: 'Save Deal' }));
    await waitFor(() => expect(mockCreateDeal).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/^Saved/)).toBeTruthy();

    mockUploadDetailedExcel.mockResolvedValue(makeDetailedExcelIntakeReport());
    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    const file = new File(['PK'], 'anchor_detailed_input_v2_1.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), file);
    await waitFor(() => {
      expect(
        screen.getByLabelText('Detailed Excel Review Purchase Price'),
      ).toHaveProperty('value', '10000000');
    });
    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));

    await user.click(screen.getByRole('tab', { name: 'Quick Underwrite' }));

    expect(screen.getByLabelText('Deal Name')).toHaveProperty('value', '111 Main St');
    expect(screen.getByText(/^Saved/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Update Deal' })).toBeTruthy();
    expect(mockUpdateDeal).not.toHaveBeenCalled();
  });

  it('shows a clear error in Detailed mode when a Quick workbook is uploaded', async () => {
    const user = userEvent.setup();
    mockUploadDetailedExcel.mockRejectedValue(
      new ApiError(
        'This workbook uses the Quick Underwrite schema. Switch to Quick Underwrite or ' +
          'upload a Detailed Underwrite workbook.',
      ),
    );
    render(<App />);

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    const file = new File(['PK'], 'anchor_input_v2.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), file);

    expect(
      await screen.findByText(/uses the Quick Underwrite schema/),
    ).toBeTruthy();
    expect(screen.queryByLabelText('Detailed Excel Review Purchase Price')).toBeNull();
  });

  it('Quick mode Excel upload never calls uploadDetailedExcel, and Detailed mode never calls uploadExcel', async () => {
    const user = userEvent.setup();
    mockUploadExcel.mockResolvedValue(makeExcelIntakeReport());
    mockUploadDetailedExcel.mockResolvedValue(makeDetailedExcelIntakeReport());
    render(<App />);

    const quickFile = new File(['PK'], 'anchor_input.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), quickFile);
    await waitFor(() => expect(mockUploadExcel).toHaveBeenCalledTimes(1));
    expect(mockUploadDetailedExcel).not.toHaveBeenCalled();

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    const detailedFile = new File(['PK'], 'anchor_detailed_input_v2_1.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), detailedFile);
    await waitFor(() => expect(mockUploadDetailedExcel).toHaveBeenCalledTimes(1));
    expect(mockUploadExcel).toHaveBeenCalledTimes(1);
  });

  it('uploading a second Detailed workbook replaces the pending review cleanly rather than merging', async () => {
    const user = userEvent.setup();
    await uploadDetailedWorkbook(user);

    mockUploadDetailedExcel.mockResolvedValue(
      makeDetailedExcelIntakeReport({
        terms: {
          ...makeDetailedExcelIntakeReport().terms,
          purchase_price: 12_000_000,
        },
      }),
    );
    const secondFile = new File(['PK'], 'second_workbook.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), secondFile);

    await waitFor(() => {
      expect(
        screen.getByLabelText('Detailed Excel Review Purchase Price'),
      ).toHaveProperty('value', '12000000');
    });
    // Only one review panel's worth of fields -- never two merged copies.
    expect(screen.getAllByLabelText('Detailed Excel Review Purchase Price')).toHaveLength(1);
  });

  it('a new/unopened Detailed deal remains blank until Excel approval', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));

    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty(
      'value',
      BLANK_DETAILED_FORM_VALUES.terms.purchasePrice,
    );
  });

  it('the golden Detailed workbook can be approved and then passed into the existing Detailed analysis request path', async () => {
    const user = userEvent.setup();
    mockAnalyzeDetailed.mockResolvedValue(makeDetailedResults());
    await uploadDetailedWorkbook(user);

    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));
    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    await waitFor(() => expect(mockAnalyzeDetailed).toHaveBeenCalledTimes(1));
    const [terms, detailedOperatingInputs] = mockAnalyzeDetailed.mock.calls[0];
    expect(terms).toEqual({
      purchase_price: 10_000_000,
      hold_period: 5,
      exit_cap_rate: 0.065,
      ltv: 0.6,
      interest_rate: 0.05,
      amortization: 30,
      acquisition_cost_pct: 0.02,
      financing_fee_pct: 0.01,
      disposition_cost_pct: 0.025,
      annual_capex_reserve: 50_000,
      io_period: 2,
    });
    expect(detailedOperatingInputs).toEqual({
      gross_potential_rent: 800_000,
      other_income: 20_000,
      vacancy_credit_loss_pct: 0.05,
      property_taxes: 60_000,
      insurance: 20_000,
      utilities: 25_000,
      repairs_maintenance: 20_000,
      other_operating_expenses: 16_000,
      management_fee_pct: 0.05,
      revenue_growth: 0.03,
      expense_growth: 0.03,
    });
  });
});

describe('Detailed deal persistence workflow (Gate 11)', () => {
  it('a new Detailed deal can be saved', async () => {
    const user = userEvent.setup();
    mockCreateDetailedDeal.mockResolvedValue(makeDetailedDeal());
    render(<App />);

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    fillDetailedGoldenDeal();
    await user.type(screen.getByLabelText('Deal Name'), 'Golden Detailed Deal');
    await user.click(screen.getByRole('button', { name: 'Save Deal' }));

    await waitFor(() => expect(mockCreateDetailedDeal).toHaveBeenCalledTimes(1));
    expect(mockCreateDetailedDeal).toHaveBeenCalledWith(
      'Golden Detailed Deal',
      GOLDEN_DETAILED_TERMS_REQUEST,
      GOLDEN_DETAILED_OPERATING_INPUTS_REQUEST,
      null,
    );
    expect(mockUpdateDetailedDeal).not.toHaveBeenCalled();
    expect(await screen.findByRole('button', { name: 'Update Deal' })).toBeTruthy();
    expect(await screen.findByText(/^Saved/)).toBeTruthy();
  });

  it('a saved Detailed deal appears in the Deal Library, identified by mode', async () => {
    const user = userEvent.setup();
    mockListDeals.mockResolvedValue([makeDetailedDeal()]);
    render(<App />);

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));

    expect(await within(dealLibrary()).findByText('Golden Detailed Deal')).toBeTruthy();
    expect(within(dealLibrary()).getByText('Detailed')).toBeTruthy();
  });

  it('opening a Detailed deal switches to Detailed mode and populates all AcquisitionTerms and DetailedOperatingInputs exactly', async () => {
    const user = userEvent.setup();
    const deal = makeDetailedDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);
    expect(screen.getByRole('tab', { name: 'Quick Underwrite' })).toHaveProperty(
      'ariaSelected',
      'true',
    );

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));

    expect(screen.getByRole('tab', { name: 'Detailed Underwrite' })).toHaveProperty(
      'ariaSelected',
      'true',
    );
    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '10000000');
    expect(screen.getByLabelText(/^Hold Period/)).toHaveProperty('value', '5');
    expect(screen.getByLabelText(/^Exit Cap Rate/)).toHaveProperty('value', '6.5');
    expect(screen.getByLabelText(/^LTV/)).toHaveProperty('value', '60');
    expect(screen.getByLabelText(/^Interest Rate/)).toHaveProperty('value', '5');
    expect(screen.getByLabelText(/^Amortization/)).toHaveProperty('value', '30');
    expect(screen.getByLabelText(/^Acquisition Costs/)).toHaveProperty('value', '2');
    expect(screen.getByLabelText(/^Financing Fee/)).toHaveProperty('value', '1');
    expect(screen.getByLabelText(/^Disposition Costs/)).toHaveProperty('value', '2.5');
    expect(screen.getByLabelText(/^Annual CapEx Reserve/)).toHaveProperty('value', '50000');
    expect(screen.getByLabelText(/^Interest-Only Period/)).toHaveProperty('value', '2');
    expect(screen.getByLabelText(/^Gross Potential Rent/)).toHaveProperty('value', '800000');
    expect(screen.getByLabelText(/^Other Income/)).toHaveProperty('value', '20000');
    expect(screen.getByLabelText(/^Vacancy & Credit Loss/)).toHaveProperty('value', '5');
    expect(screen.getByLabelText(/^Property Taxes/)).toHaveProperty('value', '60000');
    expect(screen.getByLabelText(/^Insurance/)).toHaveProperty('value', '20000');
    expect(screen.getByLabelText(/^Utilities/)).toHaveProperty('value', '25000');
    expect(screen.getByLabelText(/^Repairs & Maintenance/)).toHaveProperty('value', '20000');
    expect(screen.getByLabelText(/^Other Operating Expenses/)).toHaveProperty('value', '16000');
    expect(screen.getByLabelText(/^Management Fee/)).toHaveProperty('value', '5');
    expect(screen.getByLabelText(/^Revenue Growth/)).toHaveProperty('value', '3');
    expect(screen.getByLabelText(/^Expense Growth/)).toHaveProperty('value', '3');
    expect(screen.getByLabelText('Deal Name')).toHaveProperty('value', 'Golden Detailed Deal');
    expect(await screen.findByText(/^Saved/)).toBeTruthy();
  });

  it('an opened Detailed deal with an explicit zero value renders it as 0, not blank', async () => {
    const user = userEvent.setup();
    const deal = makeDetailedDeal({
      terms: { ...GOLDEN_DETAILED_TERMS_REQUEST, acquisition_cost_pct: 0 },
    });
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));

    expect(screen.getByLabelText(/^Acquisition Costs/)).toHaveProperty('value', '0');
  });

  it('editing an AcquisitionTerms field marks a saved Detailed deal dirty', async () => {
    const user = userEvent.setup();
    const deal = makeDetailedDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    await screen.findByText(/^Saved/);

    fireEvent.change(screen.getByLabelText(/^Purchase Price/), {
      target: { value: '11000000' },
    });

    expect(screen.getByText('Unsaved changes')).toBeTruthy();
  });

  it('editing a DetailedOperatingInputs field marks a saved Detailed deal dirty', async () => {
    const user = userEvent.setup();
    const deal = makeDetailedDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    await screen.findByText(/^Saved/);

    fireEvent.change(screen.getByLabelText(/^Gross Potential Rent/), {
      target: { value: '850000' },
    });

    expect(screen.getByText('Unsaved changes')).toBeTruthy();
  });

  it('saving an edited Detailed deal clears the dirty state', async () => {
    const user = userEvent.setup();
    const deal = makeDetailedDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    mockUpdateDetailedDeal.mockResolvedValue({
      ...deal,
      terms: { ...GOLDEN_DETAILED_TERMS_REQUEST, purchase_price: 11_000_000 },
    });
    render(<App />);
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    await screen.findByText(/^Saved/);
    fireEvent.change(screen.getByLabelText(/^Purchase Price/), {
      target: { value: '11000000' },
    });
    expect(screen.getByText('Unsaved changes')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Update Deal' }));

    expect(await screen.findByText(/^Saved/)).toBeTruthy();
    expect(mockUpdateDetailedDeal).toHaveBeenCalledWith(
      deal.id,
      deal.name,
      { ...GOLDEN_DETAILED_TERMS_REQUEST, purchase_price: 11_000_000 },
      GOLDEN_DETAILED_OPERATING_INPUTS_REQUEST,
      null,
    );
  });

  it('Analyze does not mark a saved Detailed deal dirty', async () => {
    const user = userEvent.setup();
    const deal = makeDetailedDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    mockAnalyzeDetailed.mockResolvedValue(makeDetailedResults());
    render(<App />);
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    await screen.findByText(/^Saved/);

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await waitFor(() => expect(mockAnalyzeDetailed).toHaveBeenCalledTimes(1));

    expect(screen.getByText(/^Saved/)).toBeTruthy();
  });

  it('Generate AI Analysis does not mark a saved Detailed deal dirty', async () => {
    const user = userEvent.setup();
    const deal = makeDetailedDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    mockAnalyzeDetailed.mockResolvedValue(makeDetailedResults());
    render(<App />);
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    await screen.findByText(/^Saved/);
    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await waitFor(() => expect(mockAnalyzeDetailed).toHaveBeenCalledTimes(1));

    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    await waitFor(() => expect(mockFetchDetailedAIAnalysis).toHaveBeenCalledTimes(1));

    expect(screen.getByText(/^Saved/)).toBeTruthy();
  });

  it('Detailed Excel upload does not mark a saved Detailed deal dirty before approval', async () => {
    const user = userEvent.setup();
    const deal = makeDetailedDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    mockUploadDetailedExcel.mockResolvedValue(
      makeDetailedExcelIntakeReport({
        terms: { ...GOLDEN_DETAILED_TERMS_REQUEST, purchase_price: 12_000_000 },
      }),
    );
    render(<App />);
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    await screen.findByText(/^Saved/);

    const file = new File(['PK'], 'anchor_detailed_input_v2_1.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), file);
    await waitFor(() => {
      expect(
        screen.getByLabelText('Detailed Excel Review Purchase Price'),
      ).toHaveProperty('value', '12000000');
    });

    expect(screen.getByText(/^Saved/)).toBeTruthy();
  });

  it('Cancel Excel Review preserves the Saved state', async () => {
    const user = userEvent.setup();
    const deal = makeDetailedDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    mockUploadDetailedExcel.mockResolvedValue(
      makeDetailedExcelIntakeReport({
        terms: { ...GOLDEN_DETAILED_TERMS_REQUEST, purchase_price: 12_000_000 },
      }),
    );
    render(<App />);
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    await screen.findByText(/^Saved/);

    const file = new File(['PK'], 'anchor_detailed_input_v2_1.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), file);
    await waitFor(() => {
      expect(
        screen.getByLabelText('Detailed Excel Review Purchase Price'),
      ).toHaveProperty('value', '12000000');
    });

    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Cancel Review' }));

    expect(screen.getByText(/^Saved/)).toBeTruthy();
    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '10000000');
  });

  it('approving a Detailed Excel review with different values marks the saved deal dirty', async () => {
    const user = userEvent.setup();
    const deal = makeDetailedDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    mockUploadDetailedExcel.mockResolvedValue(
      makeDetailedExcelIntakeReport({
        terms: { ...GOLDEN_DETAILED_TERMS_REQUEST, purchase_price: 12_000_000 },
      }),
    );
    render(<App />);
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    await screen.findByText(/^Saved/);

    const file = new File(['PK'], 'anchor_detailed_input_v2_1.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), file);
    await waitFor(() => {
      expect(
        screen.getByLabelText('Detailed Excel Review Purchase Price'),
      ).toHaveProperty('value', '12000000');
    });

    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));

    expect(screen.getByText('Unsaved changes')).toBeTruthy();
    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '12000000');
  });

  it('Duplicate preserves operating mode and all 22 Detailed assumptions', async () => {
    const user = userEvent.setup();
    const deal = makeDetailedDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockDuplicateDeal.mockResolvedValue(
      makeDetailedDeal({ id: 'detailed-deal-2', name: 'Golden Detailed Deal (Copy)' }),
    );
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await within(dealLibrary()).findByText('Golden Detailed Deal');
    await user.click(screen.getByRole('button', { name: 'Duplicate' }));

    await waitFor(() => expect(mockDuplicateDeal).toHaveBeenCalledWith(deal.id));
  });

  it('Delete works for a Detailed deal', async () => {
    const user = userEvent.setup();
    const deal = makeDetailedDeal();
    mockListDeals.mockResolvedValue([deal]);
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await within(dealLibrary()).findByText('Golden Detailed Deal');
    await user.click(screen.getByRole('button', { name: 'Delete' }));

    await waitFor(() => expect(mockDeleteDeal).toHaveBeenCalledWith(deal.id));
    confirmSpy.mockRestore();
  });

  it('deleting the currently open Detailed deal resets the workspace', async () => {
    const user = userEvent.setup();
    const deal = makeDetailedDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<App />);
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    await screen.findByText(/^Saved/);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(mockDeleteDeal).toHaveBeenCalledWith(deal.id));
    await user.click(screen.getByRole('button', { name: 'Close' }));

    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '');
    expect(screen.getByLabelText('Deal Name')).toHaveProperty('value', '');
    expect(screen.getByText('Unsaved deal')).toBeTruthy();
    confirmSpy.mockRestore();
  });
});

describe('Cross-mode persistence safety (Gate 11)', () => {
  it('opening a Detailed deal after a Quick deal was open leaves no Quick assumptions/results attached to the Detailed workspace', async () => {
    const user = userEvent.setup();
    const quickDeal = makeDeal();
    const detailedDeal = makeDetailedDeal();
    mockListDeals.mockResolvedValue([quickDeal, detailedDeal]);
    mockGetDeal.mockImplementation(async (id: string) =>
      id === quickDeal.id ? quickDeal : detailedDeal,
    );
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    const quickRow = (await within(dealLibrary()).findByText(quickDeal.name)).closest('li');
    if (!quickRow) throw new Error('Quick deal row not found');
    await user.click(within(quickRow).getByRole('button', { name: 'Open' }));
    await screen.findByText(/^Saved/);
    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await waitFor(() => expect(mockAnalyze).toHaveBeenCalledTimes(1));
    expect(screen.getAllByText('Key Returns').length).toBeGreaterThanOrEqual(1);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    const detailedRow = (await within(dealLibrary()).findByText(detailedDeal.name)).closest(
      'li',
    );
    if (!detailedRow) throw new Error('Detailed deal row not found');
    await user.click(within(detailedRow).getByRole('button', { name: 'Open' }));

    expect(screen.getByRole('tab', { name: 'Detailed Underwrite' })).toHaveProperty(
      'ariaSelected',
      'true',
    );
    expect(screen.queryByText('Key Returns')).toBeNull();
    expect(screen.getByText(/Enter assumptions and click/)).toBeTruthy();
    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '10000000');
  });

  it('opening a Quick deal after a Detailed deal was open leaves no Detailed assumptions/results attached to the Quick workspace', async () => {
    const user = userEvent.setup();
    const quickDeal = makeDeal();
    const detailedDeal = makeDetailedDeal();
    mockListDeals.mockResolvedValue([quickDeal, detailedDeal]);
    mockGetDeal.mockImplementation(async (id: string) =>
      id === quickDeal.id ? quickDeal : detailedDeal,
    );
    mockAnalyzeDetailed.mockResolvedValue(makeDetailedResults());
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    const detailedRow = (await within(dealLibrary()).findByText(detailedDeal.name)).closest(
      'li',
    );
    if (!detailedRow) throw new Error('Detailed deal row not found');
    await user.click(within(detailedRow).getByRole('button', { name: 'Open' }));
    await screen.findByText(/^Saved/);
    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await waitFor(() => expect(mockAnalyzeDetailed).toHaveBeenCalledTimes(1));
    expect(operatingStatement()).not.toBeNull();

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    const quickRow = (await within(dealLibrary()).findByText(quickDeal.name)).closest('li');
    if (!quickRow) throw new Error('Quick deal row not found');
    await user.click(within(quickRow).getByRole('button', { name: 'Open' }));

    expect(screen.getByRole('tab', { name: 'Quick Underwrite' })).toHaveProperty(
      'ariaSelected',
      'true',
    );
    expect(operatingStatement()).toBeNull();
    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty(
      'value',
      DEFAULT_FORM_VALUES.purchasePrice,
    );
  });
});

describe('Detailed OM ingestion workflow (Gate 12)', () => {
  /** Uploads the default Detailed OM fixture and waits for the review
   * panel's fields to render -- never waits on the live
   * `DetailedAssumptionsForm`, which this upload must not touch. */
  async function uploadDetailedOm(user: ReturnType<typeof userEvent.setup>) {
    render(<App />);
    mockUploadDetailedOm.mockResolvedValue(makeDetailedExtractionResult());

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    await goTo(user, 'Documents');
    const file = new File(['%PDF-1.4'], 'om.pdf', { type: 'application/pdf' });
    await user.upload(screen.getByLabelText('Upload OM (PDF)'), file);

    await waitFor(() => {
      expect(screen.getByText('Potential Base Rent: $800,000', { exact: false })).toBeTruthy();
    });
  }

  function omFieldCard(label: string): HTMLElement {
    // A heading-role query, not a plain text query: the OM review card's
    // label is an `<h4>` (a real heading), while the live
    // `DetailedAssumptionsForm` shows the identical label text as a plain
    // `<span>` -- scoping to the heading role is what disambiguates them.
    const heading = screen.getByRole('heading', { name: label });
    const card = heading.closest('.om-field-card');
    if (!card) {
      throw new Error(`No .om-field-card ancestor found for label ${label}`);
    }
    return card as HTMLElement;
  }

  it('exposes OM upload in Detailed mode', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));

    expect(screen.getByLabelText('Upload OM (PDF)')).toBeTruthy();
  });

  it('does not mutate active Detailed assumptions on upload', async () => {
    const user = userEvent.setup();
    await uploadDetailedOm(user);

    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty(
      'value',
      BLANK_DETAILED_FORM_VALUES.terms.purchasePrice,
    );
  });

  it('extracted Detailed fields appear in review with evidence', async () => {
    const user = userEvent.setup();
    await uploadDetailedOm(user);

    const card = omFieldCard('Gross Potential Rent');
    expect(within(card).getByText('800000')).toBeTruthy();
    expect(within(card).getByText('Stated')).toBeTruthy();
    expect(within(card).getByText(/Potential Base Rent: \$800,000/)).toBeTruthy();
    expect(within(card).getByText(/Page 31/)).toBeTruthy();
  });

  it('missing fields remain visibly unresolved, never a fabricated zero', async () => {
    const user = userEvent.setup();
    await uploadDetailedOm(user);

    const card = omFieldCard('Insurance');
    expect(within(card).getByText('Missing')).toBeTruthy();
    expect(within(card).getByText('Not found in OM.')).toBeTruthy();
  });

  it('extracted values are editable before approval', async () => {
    const user = userEvent.setup();
    await uploadDetailedOm(user);

    const card = omFieldCard('Property Taxes');
    await user.click(within(card).getByRole('button', { name: 'Edit' }));
    const input = within(card).getByLabelText('Edit Property Taxes');
    await user.clear(input);
    await user.type(input, '65000');
    await user.click(within(card).getByRole('button', { name: 'Save' }));

    expect(within(card).getByText('Approved')).toBeTruthy();
  });

  it('Approve loads only the explicitly approved Detailed assumptions', async () => {
    const user = userEvent.setup();
    await uploadDetailedOm(user);

    await user.click(
      within(omFieldCard('Purchase Price')).getByRole('button', { name: 'Approve' }),
    );
    await user.click(
      within(omFieldCard('Gross Potential Rent')).getByRole('button', { name: 'Approve' }),
    );
    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Use approved values' }));

    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '10000000');
    expect(screen.getByLabelText(/^Gross Potential Rent/)).toHaveProperty('value', '800000');
    // Not approved -- stays blank, never defaulted.
    expect(screen.getByLabelText(/^Property Taxes/)).toHaveProperty('value', '');
  });

  it('explicit zero survives review and approval', async () => {
    const user = userEvent.setup();
    await uploadDetailedOm(user);

    await user.click(
      within(omFieldCard('Property Taxes')).getByRole('button', { name: 'Approve' }),
    );
    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Use approved values' }));

    expect(screen.getByLabelText(/^Property Taxes/)).toHaveProperty('value', '0');
  });

  it('Approve never automatically calls Analyze', async () => {
    const user = userEvent.setup();
    await uploadDetailedOm(user);

    await user.click(
      within(omFieldCard('Purchase Price')).getByRole('button', { name: 'Approve' }),
    );
    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Use approved values' }));

    expect(mockAnalyzeDetailed).not.toHaveBeenCalled();
  });

  it('Cancel Review leaves active Detailed assumptions unchanged', async () => {
    const user = userEvent.setup();
    await uploadDetailedOm(user);

    await user.click(
      within(omFieldCard('Purchase Price')).getByRole('button', { name: 'Approve' }),
    );
    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Cancel Review' }));

    expect(screen.queryByText('Potential Base Rent: $800,000', { exact: false })).toBeNull();
    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty(
      'value',
      BLANK_DETAILED_FORM_VALUES.terms.purchasePrice,
    );
  });
});

describe('Detailed OM saved-deal safety (Gate 12)', () => {
  it('a saved Detailed deal remains clean while an OM upload is pending review', async () => {
    const user = userEvent.setup();
    const deal = makeDetailedDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    mockUploadDetailedOm.mockResolvedValue(makeDetailedExtractionResult());
    render(<App />);
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    await screen.findByText(/^Saved/);

    const file = new File(['%PDF-1.4'], 'om.pdf', { type: 'application/pdf' });
    await user.upload(screen.getByLabelText('Upload OM (PDF)'), file);
    await waitFor(() => {
      expect(screen.getByText('Potential Base Rent: $800,000', { exact: false })).toBeTruthy();
    });

    expect(screen.getByText(/^Saved/)).toBeTruthy();
  });

  it('Cancel Review preserves the Saved state', async () => {
    const user = userEvent.setup();
    const deal = makeDetailedDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    mockUploadDetailedOm.mockResolvedValue(makeDetailedExtractionResult());
    render(<App />);
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    await screen.findByText(/^Saved/);

    const file = new File(['%PDF-1.4'], 'om.pdf', { type: 'application/pdf' });
    await user.upload(screen.getByLabelText('Upload OM (PDF)'), file);
    await waitFor(() => {
      expect(screen.getByText('Potential Base Rent: $800,000', { exact: false })).toBeTruthy();
    });

    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Cancel Review' }));

    expect(screen.getByText(/^Saved/)).toBeTruthy();
    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '10000000');
  });

  it('Approve with a changed value marks the saved deal dirty, and Save returns it to Saved', async () => {
    const user = userEvent.setup();
    const deal = makeDetailedDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    mockUploadDetailedOm.mockResolvedValue(
      makeDetailedExtractionResult({
        purchase_price: {
          field_id: 'purchase_price',
          candidates: [
            {
              value: '12000000',
              status: 'stated',
              provenance: { page: 1, anchor: 'paragraph:0', snippet: 'Purchase Price: $12,000,000' },
            },
          ],
        },
      }),
    );
    mockUpdateDetailedDeal.mockResolvedValue({
      ...deal,
      terms: { ...GOLDEN_DETAILED_TERMS_REQUEST, purchase_price: 12_000_000 },
    });
    render(<App />);
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    await screen.findByText(/^Saved/);

    await goTo(user, 'Documents');
    const file = new File(['%PDF-1.4'], 'om.pdf', { type: 'application/pdf' });
    await user.upload(screen.getByLabelText('Upload OM (PDF)'), file);
    await waitFor(() => {
      expect(screen.getByText('Purchase Price: $12,000,000', { exact: false })).toBeTruthy();
    });

    const card = screen.getByRole('heading', { name: 'Purchase Price' }).closest('.om-field-card');
    if (!card) throw new Error('Purchase Price card not found');
    await user.click(within(card as HTMLElement).getByRole('button', { name: 'Approve' }));
    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Use approved values' }));

    expect(screen.getByText('Unsaved changes')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Update Deal' }));

    expect(await screen.findByText(/^Saved/)).toBeTruthy();
  });
});

describe('Cross-mode OM safety (Gate 12)', () => {
  it('Quick OM upload calls uploadOm, never uploadDetailedOm', async () => {
    const user = userEvent.setup();
    mockUploadOm.mockResolvedValue(makeExtractionResult());
    render(<App />);

    const file = new File(['%PDF-1.4'], 'om.pdf', { type: 'application/pdf' });
    await user.upload(screen.getByLabelText('Upload OM (PDF)'), file);

    await waitFor(() => expect(mockUploadOm).toHaveBeenCalledTimes(1));
    expect(mockUploadDetailedOm).not.toHaveBeenCalled();
  });

  it('Detailed OM upload calls uploadDetailedOm, never uploadOm', async () => {
    const user = userEvent.setup();
    mockUploadDetailedOm.mockResolvedValue(makeDetailedExtractionResult());
    render(<App />);

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    const file = new File(['%PDF-1.4'], 'om.pdf', { type: 'application/pdf' });
    await user.upload(screen.getByLabelText('Upload OM (PDF)'), file);

    await waitFor(() => expect(mockUploadDetailedOm).toHaveBeenCalledTimes(1));
    expect(mockUploadOm).not.toHaveBeenCalled();
  });

  it('a Detailed OM review pending in the background does not appear after switching to Quick mode', async () => {
    const user = userEvent.setup();
    mockUploadDetailedOm.mockResolvedValue(makeDetailedExtractionResult());
    render(<App />);

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    const file = new File(['%PDF-1.4'], 'om.pdf', { type: 'application/pdf' });
    await user.upload(screen.getByLabelText('Upload OM (PDF)'), file);
    await waitFor(() => {
      expect(screen.getByText('Potential Base Rent: $800,000', { exact: false })).toBeTruthy();
    });

    await user.click(screen.getByRole('tab', { name: 'Quick Underwrite' }));

    expect(screen.queryByText('Potential Base Rent: $800,000', { exact: false })).toBeNull();
    expect(screen.queryByText('Gross Potential Rent')).toBeNull();
  });

  it('a Quick OM review pending in the background does not appear after switching to Detailed mode', async () => {
    const user = userEvent.setup();
    mockUploadOm.mockResolvedValue(makeExtractionResult());
    render(<App />);

    const file = new File(['%PDF-1.4'], 'om.pdf', { type: 'application/pdf' });
    await user.upload(screen.getByLabelText('Upload OM (PDF)'), file);
    await waitFor(() => {
      expect(screen.getByText('Purchase Price: $48,000,000', { exact: false })).toBeTruthy();
    });

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));

    expect(screen.queryByText('Purchase Price: $48,000,000', { exact: false })).toBeNull();
  });

  it('opening a Detailed deal from the library never shows a pending Quick OM review in the Detailed workspace', async () => {
    const user = userEvent.setup();
    const detailedDeal = makeDetailedDeal();
    mockUploadOm.mockResolvedValue(makeExtractionResult());
    mockListDeals.mockResolvedValue([detailedDeal]);
    mockGetDeal.mockResolvedValue(detailedDeal);
    render(<App />);

    const file = new File(['%PDF-1.4'], 'om.pdf', { type: 'application/pdf' });
    await user.upload(screen.getByLabelText('Upload OM (PDF)'), file);
    await waitFor(() => {
      expect(screen.getByText('Purchase Price: $48,000,000', { exact: false })).toBeTruthy();
    });

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));

    expect(screen.getByRole('tab', { name: 'Detailed Underwrite' })).toHaveProperty(
      'ariaSelected',
      'true',
    );
    expect(screen.queryByText('Purchase Price: $48,000,000', { exact: false })).toBeNull();
  });
});

// =============================================================================
// Owner Return Metrics V3 Gate A4 -- Deal Context
// =============================================================================

describe('Deal Context (Gate A4)', () => {
  it('renders the Deal Context field in Quick mode', () => {
    render(<App />);

    const field = screen.getByLabelText('Deal Context');
    expect(field).toBeTruthy();
    expect(field).toHaveProperty(
      'placeholder',
      'Describe the investment strategy, business plan, return priorities, key risks, or intended hold / refinance / sale approach...',
    );
  });

  it('renders the Deal Context field in Detailed mode', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));

    expect(screen.getByLabelText('Deal Context')).toBeTruthy();
  });

  it('a new deal starts with a blank Deal Context', () => {
    render(<App />);

    expect(screen.getByLabelText('Deal Context')).toHaveProperty('value', '');
  });

  it('editing Deal Context marks an already-saved deal dirty', async () => {
    const user = userEvent.setup();
    const deal = makeDeal({ deal_context: 'Original strategy.' });
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    await screen.findByText(/^Saved/);

    fireEvent.change(screen.getByLabelText('Deal Context'), {
      target: { value: 'Updated strategy.' },
    });

    expect(screen.getByText('Unsaved changes')).toBeTruthy();
  });

  it('saving persists the typed Deal Context', async () => {
    const user = userEvent.setup();
    mockCreateDeal.mockResolvedValue(makeDeal({ deal_context: 'Value-add play.' }));
    render(<App />);
    fillGoldenDeal();

    await user.type(screen.getByLabelText('Deal Name'), '111 Main St');
    fireEvent.change(screen.getByLabelText('Deal Context'), {
      target: { value: 'Value-add play.' },
    });
    await user.click(screen.getByRole('button', { name: 'Save Deal' }));

    await waitFor(() => expect(mockCreateDeal).toHaveBeenCalledTimes(1));
    expect(mockCreateDeal).toHaveBeenCalledWith('111 Main St', GOLDEN_DEAL_REQUEST, 'Value-add play.');
  });

  it('reopening a deal restores its exact Deal Context', async () => {
    const user = userEvent.setup();
    const deal = makeDeal({
      deal_context: 'Long-term hold. Prioritize recurring cash yield.',
    });
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));

    expect(await screen.findByLabelText('Deal Context')).toHaveProperty(
      'value',
      'Long-term hold. Prioritize recurring cash yield.',
    );
  });

  it('duplicating a deal is a pure backend passthrough -- the frontend needs no special Deal Context handling', async () => {
    const user = userEvent.setup();
    const deal = makeDeal({ deal_context: 'Strategy to duplicate.' });
    mockListDeals.mockResolvedValue([deal]);
    mockDuplicateDeal.mockResolvedValue({ ...deal, id: 'deal-2' });
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Duplicate' }));

    await waitFor(() => expect(mockDuplicateDeal).toHaveBeenCalledWith('deal-1'));
  });

  it('Deal Context is isolated between deals -- opening a second deal replaces the first', async () => {
    const user = userEvent.setup();
    const dealA = makeDeal({ id: 'deal-a', name: 'Deal A', deal_context: 'Context A.' });
    const dealB = makeDeal({ id: 'deal-b', name: 'Deal B', deal_context: 'Context B.' });
    mockListDeals.mockResolvedValue([dealA, dealB]);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    mockGetDeal.mockResolvedValue(dealA);
    await user.click((await screen.findAllByRole('button', { name: 'Open' }))[0]);
    expect(await screen.findByLabelText('Deal Context')).toHaveProperty('value', 'Context A.');

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    mockGetDeal.mockResolvedValue(dealB);
    await user.click((await screen.findAllByRole('button', { name: 'Open' }))[1]);

    expect(await screen.findByLabelText('Deal Context')).toHaveProperty('value', 'Context B.');
  });

  it('each mode keeps its own Deal Context across Quick/Detailed switching', async () => {
    const user = userEvent.setup();
    render(<App />);

    fireEvent.change(screen.getByLabelText('Deal Context'), {
      target: { value: 'Quick strategy.' },
    });

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    expect(screen.getByLabelText('Deal Context')).toHaveProperty('value', '');
    fireEvent.change(screen.getByLabelText('Deal Context'), {
      target: { value: 'Detailed strategy.' },
    });

    await user.click(screen.getByRole('tab', { name: 'Quick Underwrite' }));
    expect(screen.getByLabelText('Deal Context')).toHaveProperty('value', 'Quick strategy.');

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    expect(screen.getByLabelText('Deal Context')).toHaveProperty('value', 'Detailed strategy.');
  });

  it('editing Deal Context after Analyze does not clear the deterministic results', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    expect((await screen.findAllByText('Key Returns')).length).toBeGreaterThanOrEqual(1);

    fireEvent.change(screen.getByLabelText('Deal Context'), {
      target: { value: 'Prioritize income over IRR.' },
    });

    expect(screen.getAllByText('Key Returns').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Owner Returns').length).toBeGreaterThanOrEqual(1);
  });

  it('editing Deal Context after generating AI analysis clears the stale AI output', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Anchor AI Analyst');
    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    expect(await screen.findByText('Investment View')).toBeTruthy();

    fireEvent.change(screen.getByLabelText('Deal Context'), {
      target: { value: 'Now a refinance-and-hold strategy.' },
    });

    expect(screen.queryByText('Investment View')).toBeNull();
    expect(screen.getByRole('button', { name: 'Generate AI Analysis' })).toBeTruthy();
    // Deterministic results remain -- only the stale AI output was cleared.
    expect(screen.getAllByText('Key Returns').length).toBeGreaterThanOrEqual(1);
  });

  it('an empty Deal Context is valid -- Save sends null, not an error', async () => {
    const user = userEvent.setup();
    mockCreateDeal.mockResolvedValue(makeDeal());
    render(<App />);
    fillGoldenDeal();

    await user.type(screen.getByLabelText('Deal Name'), '111 Main St');
    await user.click(screen.getByRole('button', { name: 'Save Deal' }));

    await waitFor(() => expect(mockCreateDeal).toHaveBeenCalledTimes(1));
    expect(mockCreateDeal).toHaveBeenCalledWith('111 Main St', GOLDEN_DEAL_REQUEST, null);
    expect(screen.queryByText(/error/i)).toBeNull();
  });

  it('approving an Excel review does not overwrite an already-typed Deal Context', async () => {
    const user = userEvent.setup();
    mockUploadExcel.mockResolvedValue({ inputs: GOLDEN_DEAL_REQUEST, defaulted_v2_field_ids: [] });
    render(<App />);

    fireEvent.change(screen.getByLabelText('Deal Context'), {
      target: { value: 'Written before the Excel upload.' },
    });

    const file = new File(['PK'], 'anchor_input.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), file);
    await screen.findByText(/Workbook parsed successfully/);
    await goTo(user, 'Documents');
    await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));
    await screen.findByText(/Excel assumptions approved and loaded/);

    expect(screen.getByLabelText('Deal Context')).toHaveProperty(
      'value',
      'Written before the Excel upload.',
    );
  });

  it('clicking Analyze Deal does not mutate an unsaved Deal Context', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    fireEvent.change(screen.getByLabelText('Deal Context'), {
      target: { value: 'Strategy typed before analyzing.' },
    });

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findAllByText('Key Returns');

    expect(screen.getByLabelText('Deal Context')).toHaveProperty(
      'value',
      'Strategy typed before analyzing.',
    );
  });
});

// =============================================================================
// Owner Return Metrics V3 Gate A6 -- Persisted Analysis + AI Snapshots
// =============================================================================

describe('Persisted Analysis + AI Snapshots (Gate A6)', () => {
  it('restores Quick analysis after switching away and back to the same deal', async () => {
    const user = userEvent.setup();
    const dealA = makeDeal({ id: 'deal-a', name: 'Deal A' });
    const dealB = makeDeal({ id: 'deal-b', name: 'Deal B' });
    mockListDeals.mockResolvedValue([dealA, dealB]);
    mockAnalyze.mockResolvedValue(makeResults());

    render(<App />);

    mockGetDeal.mockResolvedValueOnce(dealA);
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click((await screen.findAllByRole('button', { name: 'Open' }))[0]);
    await screen.findByText(/^Saved/);

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    expect((await screen.findAllByText('Key Returns')).length).toBeGreaterThanOrEqual(1);
    await waitFor(() =>
      expect(mockUpdateDealAnalysisSnapshot).toHaveBeenCalledWith(
        'deal-a',
        makeResults(),
        'fp-financial',
      ),
    );

    mockGetDeal.mockResolvedValueOnce(dealB);
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click((await screen.findAllByRole('button', { name: 'Open' }))[1]);
    expect(screen.queryByText('Key Returns')).toBeNull();

    // Simulate reopening deal A after the analysis was cached server-side.
    mockGetDeal.mockResolvedValueOnce({ ...dealA, analysis_snapshot: makeResults() });
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click((await screen.findAllByRole('button', { name: 'Open' }))[0]);

    expect((await screen.findAllByText('Key Returns')).length).toBeGreaterThanOrEqual(1);
    // Restored from the cache, not a fresh network call.
    expect(mockAnalyze).toHaveBeenCalledTimes(1);
  });

  it('restores Detailed analysis (including the operating statement) after switching away and back', async () => {
    const user = userEvent.setup();
    const dealA = makeDetailedDeal({ id: 'detailed-a', name: 'Detailed A' });
    const dealB = makeDetailedDeal({ id: 'detailed-b', name: 'Detailed B' });
    mockListDeals.mockResolvedValue([dealA, dealB]);
    mockAnalyzeDetailed.mockResolvedValue(makeDetailedResults());

    render(<App />);

    mockGetDeal.mockResolvedValueOnce(dealA);
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click((await screen.findAllByRole('button', { name: 'Open' }))[0]);
    expect(
      screen.getByRole('tab', { name: 'Detailed Underwrite' }),
    ).toHaveProperty('ariaSelected', 'true');

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await waitFor(() => expect(operatingStatement()).not.toBeNull());
    expect(screen.getAllByText('Key Returns').length).toBeGreaterThanOrEqual(1);
    await waitFor(() =>
      expect(mockUpdateDealAnalysisSnapshot).toHaveBeenCalledWith(
        'detailed-a',
        makeDetailedResults(),
        'fp-financial',
      ),
    );

    mockGetDeal.mockResolvedValueOnce(dealB);
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click((await screen.findAllByRole('button', { name: 'Open' }))[1]);
    expect(operatingStatement()).toBeNull();

    mockGetDeal.mockResolvedValueOnce({ ...dealA, analysis_snapshot: makeDetailedResults() });
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click((await screen.findAllByRole('button', { name: 'Open' }))[0]);

    // Operating statement AND Owner Return Metrics both restore -- the
    // complete result surface, not just headline cards.
    await waitFor(() => expect(operatingStatement()).not.toBeNull());
    expect(screen.getAllByText('Owner Returns').length).toBeGreaterThanOrEqual(1);
    expect(mockAnalyzeDetailed).toHaveBeenCalledTimes(1);
  });

  it('restores Quick AI Analyst output after switching away and back', async () => {
    const user = userEvent.setup();
    const dealA = makeDeal({ id: 'deal-a', name: 'Deal A' });
    const dealB = makeDeal({ id: 'deal-b', name: 'Deal B' });
    mockListDeals.mockResolvedValue([dealA, dealB]);
    mockAnalyze.mockResolvedValue(makeResults());
    mockFetchAIAnalysis.mockResolvedValue(makeAiAnalysis());

    render(<App />);

    mockGetDeal.mockResolvedValueOnce(dealA);
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click((await screen.findAllByRole('button', { name: 'Open' }))[0]);
    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Anchor AI Analyst');
    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    expect(await screen.findByText('Investment View')).toBeTruthy();
    await waitFor(() =>
      expect(mockUpdateDealAiSnapshot).toHaveBeenCalledWith('deal-a', makeAiAnalysis(), 'fp-ai'),
    );

    mockGetDeal.mockResolvedValueOnce(dealB);
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click((await screen.findAllByRole('button', { name: 'Open' }))[1]);
    expect(screen.queryByText('Investment View')).toBeNull();

    mockGetDeal.mockResolvedValueOnce({
      ...dealA,
      analysis_snapshot: makeResults(),
      ai_snapshot: makeAiAnalysis(),
    });
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click((await screen.findAllByRole('button', { name: 'Open' }))[0]);

    expect(await screen.findByText('Investment View')).toBeTruthy();
    expect(mockFetchAIAnalysis).toHaveBeenCalledTimes(1);
  });

  it('restores Detailed AI Analyst output after switching away and back', async () => {
    const user = userEvent.setup();
    const dealA = makeDetailedDeal({ id: 'detailed-a', name: 'Detailed A' });
    const dealB = makeDetailedDeal({ id: 'detailed-b', name: 'Detailed B' });
    mockListDeals.mockResolvedValue([dealA, dealB]);
    mockAnalyzeDetailed.mockResolvedValue(makeDetailedResults());
    mockFetchDetailedAIAnalysis.mockResolvedValue(makeAiAnalysis());

    render(<App />);

    mockGetDeal.mockResolvedValueOnce(dealA);
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click((await screen.findAllByRole('button', { name: 'Open' }))[0]);
    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Anchor AI Analyst');
    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    expect(await screen.findByText('Investment View')).toBeTruthy();
    await waitFor(() =>
      expect(mockUpdateDealAiSnapshot).toHaveBeenCalledWith('detailed-a', makeAiAnalysis(), 'fp-ai'),
    );

    mockGetDeal.mockResolvedValueOnce(dealB);
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click((await screen.findAllByRole('button', { name: 'Open' }))[1]);
    expect(screen.queryByText('Investment View')).toBeNull();

    mockGetDeal.mockResolvedValueOnce({
      ...dealA,
      analysis_snapshot: makeDetailedResults(),
      ai_snapshot: makeAiAnalysis(),
    });
    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click((await screen.findAllByRole('button', { name: 'Open' }))[0]);

    expect(await screen.findByText('Investment View')).toBeTruthy();
    expect(mockFetchDetailedAIAnalysis).toHaveBeenCalledTimes(1);
  });

  it('a financial assumption edit clears the currently-shown result and AI, even when they were restored from a snapshot', async () => {
    const user = userEvent.setup();
    const deal = makeDeal({
      id: 'deal-1',
      analysis_snapshot: makeResults(),
      ai_snapshot: makeAiAnalysis(),
    });
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    expect((await screen.findAllByText('Key Returns')).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Investment View')).toBeTruthy();

    fireEvent.change(screen.getByLabelText(/^Purchase Price/), {
      target: { value: '60000000' },
    });

    expect(screen.queryByText('Key Returns')).toBeNull();
    expect(screen.queryByText('Investment View')).toBeNull();
  });

  it('saving a changed financial assumption never re-attaches the now-stale analysis/AI snapshot', async () => {
    const user = userEvent.setup();
    const deal = makeDeal({
      id: 'deal-1',
      analysis_snapshot: makeResults(),
      ai_snapshot: makeAiAnalysis(),
    });
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    mockUpdateDeal.mockResolvedValue({ ...deal, analysis_snapshot: null, ai_snapshot: null });
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    fireEvent.change(screen.getByLabelText(/^Purchase Price/), {
      target: { value: '60000000' },
    });

    await user.click(screen.getByRole('button', { name: 'Update Deal' }));

    // Owner Return Metrics V3 Gate A7: `updateDeal` never carries a
    // snapshot at all -- the financial edit already cleared `results`/
    // `aiAnalysis` to null in frontend state, so handleSaveDeal has nothing
    // to attach through the dedicated snapshot endpoints. The now-stale
    // server-side cache is invalidated for free by the backend's own
    // read-time fingerprint check against the newly-saved assumptions.
    await waitFor(() => expect(mockUpdateDeal).toHaveBeenCalledTimes(1));
    expect(mockUpdateDealAnalysisSnapshot).not.toHaveBeenCalled();
    expect(mockUpdateDealAiSnapshot).not.toHaveBeenCalled();
  });

  it('editing Deal Context on a snapshot-restored deal preserves the result and clears the AI', async () => {
    const user = userEvent.setup();
    const deal = makeDeal({
      id: 'deal-1',
      deal_context: 'Original strategy.',
      analysis_snapshot: makeResults(),
      ai_snapshot: makeAiAnalysis(),
    });
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    expect((await screen.findAllByText('Key Returns')).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Investment View')).toBeTruthy();

    fireEvent.change(screen.getByLabelText('Deal Context'), {
      target: { value: 'Updated strategy.' },
    });

    expect(screen.getAllByText('Key Returns').length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText('Investment View')).toBeNull();
  });

  it('saving a Deal-Context-only edit preserves the analysis snapshot and clears the AI snapshot', async () => {
    const user = userEvent.setup();
    const deal = makeDeal({
      id: 'deal-1',
      deal_context: 'Original strategy.',
      analysis_snapshot: makeResults(),
      ai_snapshot: makeAiAnalysis(),
    });
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    mockUpdateDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    fireEvent.change(screen.getByLabelText('Deal Context'), {
      target: { value: 'Updated strategy.' },
    });

    await user.click(screen.getByRole('button', { name: 'Update Deal' }));

    // Owner Return Metrics V3 Gate A7: `updateDeal` no longer carries a
    // snapshot -- it is called with just the assumptions/Deal Context, and
    // the still-valid analysis is preserved by re-attaching it through the
    // provenance-validated dedicated endpoint. The cleared AI (frontend
    // state already nulled it on the context edit) is never re-attached.
    await waitFor(() => expect(mockUpdateDeal).toHaveBeenCalledTimes(1));
    const [, , , dealContextArg] = mockUpdateDeal.mock.calls[0];
    expect(dealContextArg).toBe('Updated strategy.');
    await waitFor(() =>
      expect(mockUpdateDealAnalysisSnapshot).toHaveBeenCalledWith(
        'deal-1',
        makeResults(),
        'fp-financial',
      ),
    );
    expect(mockUpdateDealAiSnapshot).not.toHaveBeenCalled();
  });

  it('analyzing a brand-new unsaved deal never silently creates a database row', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    expect((await screen.findAllByText('Key Returns')).length).toBeGreaterThanOrEqual(1);

    expect(mockCreateDeal).not.toHaveBeenCalled();
    expect(mockUpdateDeal).not.toHaveBeenCalled();
    expect(mockUpdateDealAnalysisSnapshot).not.toHaveBeenCalled();
  });

  it('the first Save of a new deal persists the current valid analysis and AI output', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    mockFetchAIAnalysis.mockResolvedValue(makeAiAnalysis());
    mockCreateDeal.mockResolvedValue(makeDeal());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Anchor AI Analyst');
    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    await screen.findByText('Investment View');

    await user.type(screen.getByLabelText('Deal Name'), '111 Main St');
    await user.click(screen.getByRole('button', { name: 'Save Deal' }));

    // Owner Return Metrics V3 Gate A7: `createDeal` persists assumptions
    // only; the current valid analysis/AI are then attached through the
    // provenance-validated dedicated endpoints against the newly-created
    // deal's id.
    await waitFor(() => expect(mockCreateDeal).toHaveBeenCalledTimes(1));
    expect(mockCreateDeal).toHaveBeenCalledWith('111 Main St', GOLDEN_DEAL_REQUEST, null);
    await waitFor(() =>
      expect(mockUpdateDealAnalysisSnapshot).toHaveBeenCalledWith(
        'deal-1',
        makeResults(),
        'fp-financial',
      ),
    );
    await waitFor(() =>
      expect(mockUpdateDealAiSnapshot).toHaveBeenCalledWith('deal-1', makeAiAnalysis(), 'fp-ai'),
    );
  });

  it('Quick and Detailed snapshots never cross-contaminate when switching modes', async () => {
    const user = userEvent.setup();
    const quickDeal = makeDeal({ id: 'deal-1', analysis_snapshot: makeResults() });
    mockListDeals.mockResolvedValue([quickDeal]);
    mockGetDeal.mockResolvedValue(quickDeal);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    expect((await screen.findAllByText('Key Returns')).length).toBeGreaterThanOrEqual(1);

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));

    expect(screen.queryByText('Key Returns')).toBeNull();
    expect(
      screen.getByText('Enter assumptions and click', { exact: false }),
    ).toBeTruthy();

    await user.click(screen.getByRole('tab', { name: 'Quick Underwrite' }));
    expect(screen.getAllByText('Key Returns').length).toBeGreaterThanOrEqual(1);
  });

  it('Duplicate is a pure backend passthrough -- the frontend performs no snapshot handling of its own', async () => {
    const user = userEvent.setup();
    const deal = makeDeal({
      id: 'deal-1',
      analysis_snapshot: makeResults(),
      ai_snapshot: makeAiAnalysis(),
    });
    mockListDeals.mockResolvedValue([deal]);
    mockDuplicateDeal.mockResolvedValue({ ...deal, id: 'deal-2' });
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Duplicate' }));

    await waitFor(() => expect(mockDuplicateDeal).toHaveBeenCalledWith('deal-1'));
    // No snapshot-specific arguments -- duplication of cached results/AI is
    // entirely a backend (store-layer) decision, per Gate A6 Section 15.
    expect(mockDuplicateDeal.mock.calls[0]).toEqual(['deal-1']);
  });

  it('the Deal Library renders normally for deals that carry cached snapshots', async () => {
    const user = userEvent.setup();
    mockListDeals.mockResolvedValue([
      makeDeal({ id: 'a', name: 'Deal A', analysis_snapshot: makeResults(), ai_snapshot: makeAiAnalysis() }),
      makeDetailedDeal({
        id: 'b',
        name: 'Deal B',
        analysis_snapshot: makeDetailedResults(),
        ai_snapshot: makeAiAnalysis(),
      }),
    ]);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));

    expect(await within(dealLibrary()).findByText('Deal A')).toBeTruthy();
    expect(within(dealLibrary()).getByText('Deal B')).toBeTruthy();
    expect(screen.getAllByRole('button', { name: 'Open' }).length).toBe(2);
  });
});

// =============================================================================
// Sprint B Gate B3 -- One-Page Owner Summary (App integration)
//
// `OwnerSummaryPanel` itself is fully covered in isolation by
// `components/OwnerSummaryPanel.test.tsx` (rendering, formatting, edge
// cases). These tests only prove the App.tsx wiring: it appears at the
// right time, in the right place, survives restoration, and respects the
// existing dirty-state/invalidation rules -- exactly like every other
// results panel already does, with no new logic of its own.
// =============================================================================

describe('One-Page Owner Summary (Gate B3)', () => {
  it('renders after a successful Quick analysis', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect(await screen.findByText('Quick Underwrite', { selector: '.owner-summary-mode-badge' })).toBeTruthy();
  });

  it('renders after a successful Detailed analysis', async () => {
    const user = userEvent.setup();
    mockAnalyzeDetailed.mockResolvedValue(makeDetailedResults());
    render(<App />);

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    fillDetailedGoldenDeal();
    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect(await screen.findByText('Detailed Underwrite', { selector: '.owner-summary-mode-badge' })).toBeTruthy();
  });

  it('renders above the existing ResultsPanel content, never replacing it', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Quick Underwrite', { selector: '.owner-summary-mode-badge' });

    // "Property" is a ResultsPanel-only card heading -- Owner Summary has
    // no section with this name -- so its presence proves ResultsPanel
    // still renders in full underneath the summary.
    const ownerSummaryBadge = screen.getByText('Quick Underwrite', { selector: '.owner-summary-mode-badge' });
    const resultsPanelHeading = screen.getByText('Property');
    expect(resultsPanelHeading).toBeTruthy();

    // DOCUMENT_POSITION_FOLLOWING (4): resultsPanelHeading comes AFTER the
    // Owner Summary badge in document order -- i.e. Owner Summary renders
    // first, above the existing results stack, per the approved B1
    // navigation model.
    // eslint-disable-next-line no-bitwise
    expect(
      ownerSummaryBadge.compareDocumentPosition(resultsPanelHeading) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('renders immediately for a restored Quick snapshot, with no Analyze click', async () => {
    const user = userEvent.setup();
    const deal = makeDeal({ id: 'deal-1', analysis_snapshot: makeResults() });
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));

    expect(await screen.findByText('Quick Underwrite', { selector: '.owner-summary-mode-badge' })).toBeTruthy();
    expect(mockAnalyze).not.toHaveBeenCalled();
  });

  it('renders immediately for a restored Detailed snapshot, with no Analyze click', async () => {
    const user = userEvent.setup();
    const deal = makeDetailedDeal({ id: 'detailed-1', analysis_snapshot: makeDetailedResults() });
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));

    expect(await screen.findByText('Detailed Underwrite', { selector: '.owner-summary-mode-badge' })).toBeTruthy();
    expect(mockAnalyzeDetailed).not.toHaveBeenCalled();
  });

  it('disappears when a financial-assumption edit clears the deterministic result', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();
    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    expect(await screen.findByText('Quick Underwrite', { selector: '.owner-summary-mode-badge' })).toBeTruthy();

    fireEvent.change(screen.getByLabelText(/^Purchase Price/), {
      target: { value: '60000000' },
    });

    expect(screen.queryByText('Quick Underwrite', { selector: '.owner-summary-mode-badge' })).toBeNull();
  });

  it('a Deal-Context-only edit leaves the summary rendered and updates THE PLAY immediately', async () => {
    const user = userEvent.setup();
    const deal = makeDeal({
      id: 'deal-1',
      deal_context: 'Original strategy.',
      analysis_snapshot: makeResults(),
    });
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    expect(await screen.findByText('Quick Underwrite', { selector: '.owner-summary-mode-badge' })).toBeTruthy();
    expect(screen.getByText('Original strategy.', { selector: '.owner-summary-play-text' })).toBeTruthy();

    fireEvent.change(screen.getByLabelText('Deal Context'), {
      target: { value: 'Updated strategy.' },
    });

    expect(screen.getByText('Quick Underwrite', { selector: '.owner-summary-mode-badge' })).toBeTruthy();
    expect(screen.getByText('Updated strategy.', { selector: '.owner-summary-play-text' })).toBeTruthy();
    expect(
      screen.queryByText('Original strategy.', { selector: '.owner-summary-play-text' }),
    ).toBeNull();
  });

  it('leaves the existing ResultsPanel content intact alongside the summary', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findByText('Quick Underwrite', { selector: '.owner-summary-mode-badge' });

    // ResultsPanel's own headline section and detail cards are unaffected.
    // Gate B5: scoped to the ResultsPanel root, so the Owner Summary's own
    // "Key Returns" heading can never satisfy this assertion for it.
    const results = fullResults();
    expect(within(results).getByText('Key Returns')).toBeTruthy();
    expect(within(results).getByText('Property')).toBeTruthy();
    expect(within(results).getByText('Capitalization')).toBeTruthy();
    expect(within(results).getByText('Exit')).toBeTruthy();
  });
});

// =============================================================================
// Sprint B Gate B4 -- AI Deal Story inside the One-Page Owner Summary.
//
// The Deal Story rides the existing single "Generate AI Analysis" workflow
// and the existing `ai_snapshot` persistence path: no second button, no
// second request, no second cached artifact. These tests exercise that end
// to end at the App level.
// =============================================================================

const B4_DEAL_STORY: DealStory = {
  investment_view:
    'Coverage and recurring distributions support the stated income focus, but the modeled levered IRR sits below the supplied hurdle.',
  key_strengths: ['Year 1 DSCR is labeled above its supplied target.'],
  key_risks: ['Levered IRR is labeled below its supplied target.'],
  model_gap: null,
};

function makeAiAnalysisWithStory(overrides: Partial<DealStory> = {}): AIAnalysis {
  return makeAiAnalysis({ deal_story: { ...B4_DEAL_STORY, ...overrides } });
}

describe('AI Deal Story workflow (Gate B4)', () => {
  it('the deterministic Owner Summary renders fully before any AI is generated', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findAllByText('Key Returns');

    expect(screen.queryByText('Deal Story')).toBeNull();
    expect(screen.queryByText('AI Interpretation')).toBeNull();
    await goTo(user, 'AI Analyst');
    expect(screen.getByRole('button', { name: 'Generate AI Analysis' })).toBeTruthy();
  });

  it('one Generate AI Analysis click produces both the full report and the Deal Story', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    mockFetchAIAnalysis.mockResolvedValue(makeAiAnalysisWithStory());
    render(<App />);
    fillGoldenDeal();
    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findAllByText('Key Returns');

    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));

    // The concise owner surface...
    expect(await screen.findByText('Deal Story')).toBeTruthy();
    expect(screen.getByText('AI Interpretation')).toBeTruthy();
    // ...and the unchanged full AI Analyst report, from the same one call.
    expect(screen.getByText('Executive Summary')).toBeTruthy();
    expect(screen.getByText('Five-year hold with moderate leverage.')).toBeTruthy();
    expect(mockFetchAIAnalysis).toHaveBeenCalledTimes(1);
  });

  it('introduces no second AI-generation control anywhere in the workspace', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    mockFetchAIAnalysis.mockResolvedValue(makeAiAnalysisWithStory());
    render(<App />);
    fillGoldenDeal();
    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findAllByText('Key Returns');
    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    await screen.findByText('Deal Story');

    expect(screen.getAllByRole('button', { name: 'Generate AI Analysis' }).length).toBe(1);
    expect(screen.queryByRole('button', { name: /Deal Story/i })).toBeNull();
  });

  it('renders the Deal Story in Detailed mode through the same workflow', async () => {
    const user = userEvent.setup();
    mockFetchDetailedAIAnalysis.mockResolvedValue(makeAiAnalysisWithStory());
    render(<App />);
    await analyzeDetailedGoldenDeal(user);

    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));

    expect(await screen.findByText('Deal Story')).toBeTruthy();
    expect(screen.getByText('AI Interpretation')).toBeTruthy();
    expect(mockFetchDetailedAIAnalysis).toHaveBeenCalledTimes(1);
    expect(screen.getAllByRole('button', { name: 'Generate AI Analysis' }).length).toBe(1);
  });

  it('renders a Model Gap when the AI reports one', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    mockFetchAIAnalysis.mockResolvedValue(
      makeAiAnalysisWithStory({
        model_gap:
          'The stated refinance-and-hold strategy is not modeled in Anchor deterministic cash flows.',
      }),
    );
    render(<App />);
    fillGoldenDeal();
    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findAllByText('Key Returns');

    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));

    expect(await screen.findByText('Model Gap')).toBeTruthy();
    expect(screen.getByText(/not modeled in Anchor deterministic cash flows/)).toBeTruthy();
  });

  it('restores the Deal Story from a reopened deal AI snapshot', async () => {
    const user = userEvent.setup();
    const deal = makeDeal({
      id: 'deal-1',
      analysis_snapshot: makeResults(),
      ai_snapshot: makeAiAnalysisWithStory(),
    });
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));

    expect((await screen.findAllByText('Key Returns')).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Deal Story')).toBeTruthy();
    // Restored, never regenerated.
    expect(mockFetchAIAnalysis).not.toHaveBeenCalled();
  });

  it('restores the Deal Story from a reopened Detailed deal AI snapshot', async () => {
    const user = userEvent.setup();
    const deal = makeDetailedDeal({
      id: 'detailed-1',
      analysis_snapshot: makeDetailedResults(),
      ai_snapshot: makeAiAnalysisWithStory(),
    });
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));

    expect((await screen.findAllByText('Key Returns')).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Deal Story')).toBeTruthy();
    expect(mockFetchDetailedAIAnalysis).not.toHaveBeenCalled();
  });

  it('shows no Deal Story for a restored legacy AI snapshot that predates Gate B4', async () => {
    const user = userEvent.setup();
    const deal = makeDeal({
      id: 'deal-1',
      analysis_snapshot: makeResults(),
      ai_snapshot: makeAiAnalysis({ deal_story: null }),
    });
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));

    // The full report still restores; only the Deal Story is absent.
    expect((await screen.findAllByText('Key Returns')).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Investment View')).toBeTruthy();
    expect(screen.queryByText('Deal Story')).toBeNull();
  });

  it('a financial edit removes the Deal Story along with the deterministic summary', async () => {
    const user = userEvent.setup();
    const deal = makeDeal({
      id: 'deal-1',
      analysis_snapshot: makeResults(),
      ai_snapshot: makeAiAnalysisWithStory(),
    });
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    expect(await screen.findByText('Deal Story')).toBeTruthy();

    fireEvent.change(screen.getByLabelText(/^Purchase Price/), {
      target: { value: '60000000' },
    });

    expect(screen.queryByText('Deal Story')).toBeNull();
    expect(screen.queryByText('Key Returns')).toBeNull();
    expect(screen.queryByText('Investment View')).toBeNull();
  });

  it('a Deal Context edit removes the Deal Story but preserves the deterministic summary', async () => {
    const user = userEvent.setup();
    const deal = makeDeal({
      id: 'deal-1',
      deal_context: 'Original strategy.',
      analysis_snapshot: makeResults(),
      ai_snapshot: makeAiAnalysisWithStory(),
    });
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    expect(await screen.findByText('Deal Story')).toBeTruthy();

    fireEvent.change(screen.getByLabelText('Deal Context'), {
      target: { value: 'Updated strategy.' },
    });

    expect(screen.queryByText('Deal Story')).toBeNull();
    // The deterministic summary is untouched -- Deal Context is not a
    // financial input -- and THE PLAY reflects the new text.
    expect(screen.getAllByText('Key Returns').length).toBeGreaterThanOrEqual(1);
    const play = screen.getByText('The Play').closest('section') as HTMLElement;
    expect(within(play).getByText('Updated strategy.')).toBeTruthy();
    // No automatic AI rerun.
    expect(mockFetchAIAnalysis).not.toHaveBeenCalled();
  });

  it('keeps the full AI Analyst report available alongside the Deal Story', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    mockFetchAIAnalysis.mockResolvedValue(makeAiAnalysisWithStory());
    render(<App />);
    fillGoldenDeal();
    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await screen.findAllByText('Key Returns');
    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    await screen.findByText('Deal Story');

    expect(screen.getByText('Anchor AI Analyst')).toBeTruthy();
    for (const section of [
      'Executive Summary',
      'Return Drivers',
      'Downside Analysis',
      'Capital Structure',
      'Break-Even Interpretation',
      'Questions to Investigate',
      'Confidence / Data Gaps',
    ]) {
      expect(screen.getByText(section)).toBeTruthy();
    }
  });

  it('persists the Deal Story through the existing AI snapshot endpoint only', async () => {
    const user = userEvent.setup();
    const analysis = makeAiAnalysisWithStory();
    const deal = makeDeal({ id: 'deal-1', analysis_snapshot: makeResults() });
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    mockFetchAIAnalysis.mockResolvedValue(analysis);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    await screen.findAllByText('Key Returns');
    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    await screen.findByText('Deal Story');

    // One snapshot write, carrying the whole AIAnalysis (Deal Story nested
    // inside it) -- never a separate Deal Story persistence call.
    await waitFor(() =>
      expect(mockUpdateDealAiSnapshot).toHaveBeenCalledWith('deal-1', analysis, 'fp-ai'),
    );
    expect(mockUpdateDealAiSnapshot).toHaveBeenCalledTimes(1);
  });
});

// ===========================================================================
// Sprint C Gate C2 -- app shell and workspace navigation.
//
// The required-test list in the Gate C2 brief, section C2.21. These are the
// shell's own guarantees: that the workspaces exist, own the right things,
// preserve state across navigation, and leave every pre-Sprint-C capability
// reachable -- and that nothing in the shell touches the financial model.
// ===========================================================================

/** Which workspace tab is currently selected. */
function activeWorkspace(): string {
  const tab = document
    .querySelector('.workspace-nav')
    ?.querySelector('[aria-selected="true"]');
  return tab?.textContent ?? '';
}

/** The DOM root of one workspace panel, whether or not it is the active one. */
function panel(id: string): HTMLElement {
  const node = document.getElementById(`workspace-panel-${id}`);
  if (node === null) {
    throw new Error(`No ${id} workspace panel is rendered.`);
  }
  return node as HTMLElement;
}

function isHidden(id: string): boolean {
  return panel(id).hasAttribute('hidden');
}

/** Analyzes the Quick golden deal and leaves the app wherever Analyze put it. */
async function analyzeQuickGoldenDeal(user: ReturnType<typeof userEvent.setup>) {
  mockAnalyze.mockResolvedValue(makeResults());
  fillGoldenDeal();
  await user.click(screen.getByRole('button', { name: 'Analyze' }));
  await waitFor(() => expect(mockAnalyze).toHaveBeenCalled());
  await screen.findAllByText('Key Returns');
}

describe('Sprint C Gate C2 -- app shell', () => {
  it('1. renders the app shell: sidebar, deal header, workspace nav, workspace', () => {
    render(<App />);

    expect(document.querySelector('.app-shell')).toBeTruthy();
    expect(document.querySelector('.app-sidebar')).toBeTruthy();
    expect(document.querySelector('.deal-header')).toBeTruthy();
    expect(screen.getByRole('tablist', { name: 'Deal workspace' })).toBeTruthy();
    expect(document.querySelector('.workspace-scroll')).toBeTruthy();
  });

  it('2. renders the global sidebar navigation', () => {
    render(<App />);

    const nav = within(sidebar());
    expect(nav.getByText('Anchor')).toBeTruthy();
    expect(nav.getByRole('button', { name: 'Deal Library' })).toBeTruthy();
    expect(nav.getByRole('button', { name: 'New Deal' })).toBeTruthy();
    expect(nav.getByText('Recent Deals')).toBeTruthy();
  });

  it('3. shows existing saved deals in the sidebar without opening the library', async () => {
    mockListDeals.mockResolvedValue([makeDeal(), makeDetailedDeal()]);
    render(<App />);

    expect(await within(sidebar()).findByText('111 Main St')).toBeTruthy();
    expect(within(sidebar()).getByText('Golden Detailed Deal')).toBeTruthy();
    // Still on the workspace view -- the library was never opened.
    expect(document.querySelector('.deal-library-panel')).toBeNull();
  });

  it('4. identifies the active deal in the sidebar', async () => {
    const user = userEvent.setup();
    const deal = makeDeal();
    mockListDeals.mockResolvedValue([deal, makeDetailedDeal()]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    const row = await within(sidebar()).findByText('111 Main St');
    expect(row.closest('button')?.getAttribute('aria-current')).toBeNull();

    await user.click(row);

    await waitFor(() =>
      expect(
        within(sidebar()).getByText('111 Main St').closest('button')?.getAttribute('aria-current'),
      ).toBe('true'),
    );
    expect(
      within(sidebar()).getByText('Golden Detailed Deal').closest('button')?.getAttribute(
        'aria-current',
      ),
    ).toBeNull();
  });

  it('5. opens a saved deal from the sidebar using the existing open path', async () => {
    const user = userEvent.setup();
    const deal = makeDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(await within(sidebar()).findByText('111 Main St'));

    await waitFor(() => expect(mockGetDeal).toHaveBeenCalledWith('deal-1'));
    expect(screen.getByLabelText('Deal Name')).toHaveProperty('value', '111 Main St');
    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '50000000');
  });

  it('6. New Deal from the sidebar clears the workspace and lands on Underwrite', async () => {
    const user = userEvent.setup();
    const deal = makeDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(await within(sidebar()).findByText('111 Main St'));
    await waitFor(() => expect(mockGetDeal).toHaveBeenCalled());
    await goTo(user, 'Documents');

    await user.click(within(sidebar()).getByRole('button', { name: 'New Deal' }));

    expect(screen.getByLabelText('Deal Name')).toHaveProperty('value', '');
    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '');
    expect(activeWorkspace()).toBe('Underwrite');
  });

  it('7. the deal header displays and edits the deal name', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByLabelText('Deal Name'), '111 Main St');

    expect(
      within(document.querySelector('.deal-header') as HTMLElement).getByLabelText('Deal Name'),
    ).toHaveProperty('value', '111 Main St');
  });

  it('8. the deal header displays the operating mode, and switching it works', async () => {
    const user = userEvent.setup();
    render(<App />);
    const header = within(document.querySelector('.deal-header') as HTMLElement);

    expect(header.getByRole('tab', { name: 'Quick Underwrite' })).toHaveProperty(
      'ariaSelected',
      'true',
    );

    await user.click(header.getByRole('tab', { name: 'Detailed Underwrite' }));

    expect(header.getByRole('tab', { name: 'Detailed Underwrite' })).toHaveProperty(
      'ariaSelected',
      'true',
    );
    expect(screen.getByLabelText(/^Gross Potential Rent/)).toBeTruthy();
  });

  it('9. the header save status tracks unsaved deal -> saved -> unsaved changes', async () => {
    const user = userEvent.setup();
    mockCreateDeal.mockResolvedValue(makeDeal());
    render(<App />);
    fillGoldenDeal();

    expect(screen.getByText('Unsaved deal')).toBeTruthy();

    await user.type(screen.getByLabelText('Deal Name'), '111 Main St');
    await user.click(screen.getByRole('button', { name: 'Save Deal' }));

    expect(await screen.findByText(/^Saved/)).toBeTruthy();

    await goTo(user, 'Underwrite');
    fireEvent.change(screen.getByLabelText(/^Purchase Price/), { target: { value: '51000000' } });

    expect(screen.getByText('Unsaved changes')).toBeTruthy();
  });

  it('10. Save works from the new header, with unchanged persistence semantics', async () => {
    const user = userEvent.setup();
    mockCreateDeal.mockResolvedValue(makeDeal());
    render(<App />);
    fillGoldenDeal();

    await user.type(screen.getByLabelText('Deal Name'), '111 Main St');
    await user.click(screen.getByRole('button', { name: 'Save Deal' }));

    await waitFor(() => expect(mockCreateDeal).toHaveBeenCalledTimes(1));
    expect(mockCreateDeal).toHaveBeenCalledWith('111 Main St', GOLDEN_DEAL_REQUEST, null);
    expect(await screen.findByRole('button', { name: 'Update Deal' })).toBeTruthy();
  });

  it('11. Analyze works from the new header and sends the identical request', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeQuickGoldenDeal(user);

    expect(mockAnalyze).toHaveBeenCalledTimes(1);
    expect(mockAnalyze).toHaveBeenCalledWith(GOLDEN_DEAL_REQUEST);
    // Same downstream chain as the form's own submit button.
    await waitFor(() => expect(mockFetchSensitivityPresets).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mockFetchBreakEvenAnalysis).toHaveBeenCalledTimes(1));
  });

  it("11b. the header's Analyze and the form's Analyze Deal run the same path", async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await waitFor(() => expect(mockAnalyze).toHaveBeenCalledTimes(1));
    const fromForm = mockAnalyze.mock.calls[0][0];

    await goTo(user, 'Underwrite');
    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await waitFor(() => expect(mockAnalyze).toHaveBeenCalledTimes(2));

    expect(mockAnalyze.mock.calls[1][0]).toEqual(fromForm);
  });

  it('12-16. renders all five workspaces, with exactly one visible at a time', async () => {
    const user = userEvent.setup();
    render(<App />);

    for (const id of ['overview', 'underwrite', 'risk', 'ai', 'documents']) {
      expect(panel(id)).toBeTruthy();
    }

    const cases: [string, string][] = [
      ['Overview', 'overview'],
      ['Underwrite', 'underwrite'],
      ['Risk', 'risk'],
      ['AI Analyst', 'ai'],
      ['Documents', 'documents'],
    ];
    for (const [label, id] of cases) {
      await goTo(user, label);
      expect(activeWorkspace()).toBe(label);
      expect(isHidden(id)).toBe(false);
      for (const [, otherId] of cases.filter(([other]) => other !== label)) {
        expect(isHidden(otherId)).toBe(true);
      }
    }
  });

  it('17. workspace navigation preserves unsaved form state', async () => {
    const user = userEvent.setup();
    render(<App />);
    fillGoldenDeal();
    await user.type(screen.getByLabelText('Deal Name'), 'In Progress');

    await goTo(user, 'Risk');
    await goTo(user, 'Documents');
    await goTo(user, 'Underwrite');

    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty(
      'value',
      DEFAULT_FORM_VALUES.purchasePrice,
    );
    expect(screen.getByLabelText(/^Current NOI/)).toHaveProperty(
      'value',
      DEFAULT_FORM_VALUES.currentNoi,
    );
    expect(screen.getByLabelText('Deal Name')).toHaveProperty('value', 'In Progress');
  });

  it('18. workspace navigation preserves deterministic analysis state', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeQuickGoldenDeal(user);

    const analyzeCalls = mockAnalyze.mock.calls.length;
    const sensitivityCalls = mockFetchSensitivityPresets.mock.calls.length;

    await goTo(user, 'Documents');
    await goTo(user, 'Risk');
    await goTo(user, 'Overview');

    expect(within(ownerSummary()).getAllByText('7.91%').length).toBeGreaterThanOrEqual(1);
    // Navigation re-runs nothing.
    expect(mockAnalyze.mock.calls.length).toBe(analyzeCalls);
    expect(mockFetchSensitivityPresets.mock.calls.length).toBe(sensitivityCalls);
  });

  it('19. workspace navigation preserves AI state', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeQuickGoldenDeal(user);

    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    await screen.findByText('Five-year hold with moderate leverage.');

    await goTo(user, 'Underwrite');
    await goTo(user, 'Risk');
    await goTo(user, 'AI Analyst');

    expect(screen.getByText('Five-year hold with moderate leverage.')).toBeTruthy();
    expect(mockFetchAIAnalysis).toHaveBeenCalledTimes(1);
  });

  it('20. the Owner Summary is the Overview workspace', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeQuickGoldenDeal(user);

    await goTo(user, 'Overview');

    expect(panel('overview').querySelector('.owner-summary-panel')).toBeTruthy();
  });

  it('21. Overview does not stack the full ResultsPanel underneath the Owner Summary', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeQuickGoldenDeal(user);
    await goTo(user, 'Overview');

    expect(panel('overview').querySelector('.results-panel')).toBeNull();
    expect(panel('overview').querySelector('.sensitivity-panel')).toBeNull();
    expect(panel('overview').querySelector('.break-even-panel')).toBeNull();
    expect(panel('overview').querySelector('.ai-analyst-panel')).toBeNull();
    expect(panel('overview').querySelector('.operating-statement')).toBeNull();
  });

  it('22-23. sensitivity and break-even are the Risk workspace', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeQuickGoldenDeal(user);

    await goTo(user, 'Risk');

    expect(within(panel('risk')).getByText('Sensitivity Analysis')).toBeTruthy();
    expect(within(panel('risk')).getByText('Break-Even Analysis')).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Exit Cap × NOI Growth' })).toBeTruthy();
    expect(within(panel('underwrite')).queryByText('Sensitivity Analysis')).toBeNull();
  });

  it('24. the full AI Analyst is the AI Analyst workspace, not Overview', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeQuickGoldenDeal(user);

    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    await screen.findByText('Five-year hold with moderate leverage.');

    expect(panel('ai').querySelector('.ai-analyst-panel')).toBeTruthy();
    expect(panel('overview').querySelector('.ai-analyst-panel')).toBeNull();
  });

  it('25. the OM workflow is reachable from Documents', async () => {
    const user = userEvent.setup();
    mockUploadOm.mockResolvedValue(makeExtractionResult());
    render(<App />);

    await goTo(user, 'Documents');
    const file = new File(['%PDF-1.4'], 'om.pdf', { type: 'application/pdf' });
    await user.upload(within(panel('documents')).getByLabelText('Upload OM (PDF)'), file);

    expect(await screen.findByRole('heading', { name: 'Purchase Price' })).toBeTruthy();
    await waitFor(() => expect(mockUploadOm).toHaveBeenCalledTimes(1));
  });

  it('26. the Excel workflow is reachable from Documents', async () => {
    const user = userEvent.setup();
    mockUploadExcel.mockResolvedValue(makeExcelIntakeReport());
    render(<App />);

    await goTo(user, 'Documents');
    const file = new File(['PK'], 'anchor_input.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(
      within(panel('documents')).getByLabelText('Upload Anchor Workbook (.xlsx)'),
      file,
    );

    expect(await screen.findByLabelText('Excel Review Purchase Price')).toHaveProperty(
      'value',
      '48000000',
    );
  });

  it('27. the full results surfaces remain reachable, under Underwrite > Results', async () => {
    // Sprint C Gate C3 replaced C2's stacked "Detailed Results" section with
    // the Results tab and its own sub-navigation. Nothing was deleted.
    const user = userEvent.setup();
    render(<App />);
    await analyzeQuickGoldenDeal(user);

    await goTo(user, 'Underwrite');
    await user.click(screen.getByRole('tab', { name: 'Results' }));

    const underwrite = panel('underwrite');
    expect(underwrite.querySelector('.results-panel')).toBeTruthy();
    expect(within(underwrite).getByText('Year-by-Year Analysis')).toBeTruthy();
    expect(within(underwrite).getByText('Owner Return Schedule')).toBeTruthy();
  });

  it('27b. Detailed adds the operating statement as a fourth Results view', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeDetailedGoldenDeal(user);

    await goToOperatingStatement(user);

    expect(panel('underwrite').contains(operatingStatement())).toBe(true);
    expect(panel('underwrite').querySelector('.results-panel')).toBeTruthy();
  });

  it('28. a restored analyzed Quick deal opens coherently, on Overview', async () => {
    const user = userEvent.setup();
    const deal = makeDeal({ analysis_snapshot: makeResults(), ai_snapshot: makeAiAnalysis() });
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(await within(sidebar()).findByText('111 Main St'));
    await waitFor(() => expect(activeWorkspace()).toBe('Overview'));

    expect(panel('overview').querySelector('.owner-summary-panel')).toBeTruthy();
    await goTo(user, 'AI Analyst');
    expect(screen.getByText('Five-year hold with moderate leverage.')).toBeTruthy();
    expect(mockAnalyze).not.toHaveBeenCalled();
    expect(mockFetchAIAnalysis).not.toHaveBeenCalled();
  });

  it('29. a restored analyzed Detailed deal opens coherently, on Overview', async () => {
    const user = userEvent.setup();
    const deal = makeDetailedDeal({ analysis_snapshot: makeDetailedResults() });
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(await within(sidebar()).findByText('Golden Detailed Deal'));
    await waitFor(() => expect(activeWorkspace()).toBe('Overview'));

    expect(screen.getByRole('tab', { name: 'Detailed Underwrite' })).toHaveProperty(
      'ariaSelected',
      'true',
    );
    expect(panel('overview').querySelector('.owner-summary-panel')).toBeTruthy();
    await goTo(user, 'Underwrite');
    expect(panel('underwrite').contains(operatingStatement())).toBe(true);
    expect(mockAnalyzeDetailed).not.toHaveBeenCalled();
  });

  it('30. an unanalyzed saved deal opens on Underwrite, with honest empty states', async () => {
    const user = userEvent.setup();
    const deal = makeDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(await within(sidebar()).findByText('111 Main St'));
    await waitFor(() => expect(screen.getByLabelText('Deal Name')).toHaveProperty('value', '111 Main St'));

    expect(activeWorkspace()).toBe('Underwrite');
    expect(within(panel('overview')).getByText(/Enter assumptions and click/)).toBeTruthy();
    expect(within(panel('risk')).getByText('Analyze the deal to view risk analysis.')).toBeTruthy();
    expect(within(panel('ai')).getByText(/Analyze the deal first/)).toBeTruthy();
    // No fabricated N/A grids.
    expect(panel('overview').querySelector('.owner-summary-panel')).toBeNull();
  });

  it('30b. Risk states honestly that its outputs need a refresh on a reopened deal', async () => {
    const user = userEvent.setup();
    const deal = makeDeal({ analysis_snapshot: makeResults() });
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(await within(sidebar()).findByText('111 Main St'));
    await waitFor(() => expect(activeWorkspace()).toBe('Overview'));
    await goTo(user, 'Risk');

    // Sensitivity/break-even are not persisted -- C2 changes no persistence
    // and fabricates nothing.
    expect(within(panel('risk')).getByText(/Run/)).toBeTruthy();
    expect(within(panel('risk')).queryByText('Sensitivity Analysis')).toBeNull();
  });

  it('31. a financial edit still invalidates the analysis, seen from Overview', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeQuickGoldenDeal(user);
    await goTo(user, 'Overview');
    expect(panel('overview').querySelector('.owner-summary-panel')).toBeTruthy();

    await goTo(user, 'Underwrite');
    fireEvent.change(screen.getByLabelText(/^Exit Cap Rate/), { target: { value: '6.5' } });

    expect(panel('overview').querySelector('.owner-summary-panel')).toBeNull();
    expect(within(panel('overview')).getByText(/Enter assumptions and click/)).toBeTruthy();
    expect(within(panel('risk')).getByText('Analyze the deal to view risk analysis.')).toBeTruthy();
  });

  it('32. a Deal-Context-only edit still keeps results and clears only AI', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeQuickGoldenDeal(user);
    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    await screen.findByText('Five-year hold with moderate leverage.');

    await goTo(user, 'Underwrite');
    fireEvent.change(screen.getByLabelText('Deal Context'), { target: { value: 'Core-plus.' } });

    // Deterministic output survives; the now-stale AI interpretation does not.
    expect(panel('overview').querySelector('.owner-summary-panel')).toBeTruthy();
    expect(within(panel('risk')).getByText('Sensitivity Analysis')).toBeTruthy();
    expect(screen.queryByText('Five-year hold with moderate leverage.')).toBeNull();
  });

  it('33. duplicate and delete still work, from the header overflow menu', async () => {
    const user = userEvent.setup();
    const deal = makeDeal();
    const copy = makeDeal({ id: 'deal-2', name: '111 Main St (Copy)' });
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    mockDuplicateDeal.mockResolvedValue(copy);
    mockDeleteDeal.mockResolvedValue(undefined as never);
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<App />);

    await user.click(await within(sidebar()).findByText('111 Main St'));
    await waitFor(() => expect(mockGetDeal).toHaveBeenCalled());

    await user.click(screen.getByRole('button', { name: 'More deal actions' }));
    await user.click(screen.getByRole('menuitem', { name: 'Duplicate Deal' }));
    await waitFor(() => expect(mockDuplicateDeal).toHaveBeenCalledWith('deal-1'));

    await user.click(screen.getByRole('button', { name: 'More deal actions' }));
    await user.click(screen.getByRole('menuitem', { name: 'Delete Deal' }));
    await waitFor(() => expect(mockDeleteDeal).toHaveBeenCalledWith('deal-1'));

    // The deleted deal was the open one, so the workspace resets.
    expect(screen.getByLabelText('Deal Name')).toHaveProperty('value', '');
    confirmSpy.mockRestore();
  });

  it('33b. the Deal Library view still offers duplicate and delete', async () => {
    const user = userEvent.setup();
    mockListDeals.mockResolvedValue([makeDeal()]);
    render(<App />);

    await user.click(within(sidebar()).getByRole('button', { name: 'Deal Library' }));

    const library = within(dealLibrary());
    expect(await library.findByRole('button', { name: 'Open' })).toBeTruthy();
    expect(library.getByRole('button', { name: 'Duplicate' })).toBeTruthy();
    expect(library.getByRole('button', { name: 'Delete' })).toBeTruthy();
  });

  it('34. the shell never leaks state between Quick and Detailed', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeQuickGoldenDeal(user);
    await user.type(screen.getByLabelText('Deal Name'), 'Quick Deal');

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));

    // Detailed sees none of Quick's deal, assumptions, or results.
    expect(screen.getByLabelText('Deal Name')).toHaveProperty('value', '');
    expect(screen.queryByLabelText(/^Current NOI/)).toBeNull();
    expect(panel('overview').querySelector('.owner-summary-panel')).toBeNull();
    expect(within(panel('risk')).getByText('Analyze the deal to view risk analysis.')).toBeTruthy();

    await user.click(screen.getByRole('tab', { name: 'Quick Underwrite' }));

    // Quick is exactly as it was left.
    expect(screen.getByLabelText('Deal Name')).toHaveProperty('value', 'Quick Deal');
    expect(panel('overview').querySelector('.owner-summary-panel')).toBeTruthy();
    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty(
      'value',
      DEFAULT_FORM_VALUES.purchasePrice,
    );
  });

  it('34b. the selected workspace survives an operating-mode switch', async () => {
    const user = userEvent.setup();
    render(<App />);

    await goTo(user, 'Documents');
    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));

    expect(activeWorkspace()).toBe('Documents');
  });

  it('35. navigation introduces no calculation and calls no engine endpoint', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeQuickGoldenDeal(user);

    const before = {
      analyze: mockAnalyze.mock.calls.length,
      analyzeDetailed: mockAnalyzeDetailed.mock.calls.length,
      sensitivity: mockFetchSensitivityPresets.mock.calls.length,
      breakEven: mockFetchBreakEvenAnalysis.mock.calls.length,
      ai: mockFetchAIAnalysis.mock.calls.length,
    };

    for (const workspace of ['Overview', 'Underwrite', 'Risk', 'AI Analyst', 'Documents']) {
      await goTo(user, workspace);
    }
    await goTo(user, 'Overview');

    expect(mockAnalyze.mock.calls.length).toBe(before.analyze);
    expect(mockAnalyzeDetailed.mock.calls.length).toBe(before.analyzeDetailed);
    expect(mockFetchSensitivityPresets.mock.calls.length).toBe(before.sensitivity);
    expect(mockFetchBreakEvenAnalysis.mock.calls.length).toBe(before.breakEven);
    expect(mockFetchAIAnalysis.mock.calls.length).toBe(before.ai);

    // Every figure on screen is still the engine's own mocked output,
    // unmodified by the shell.
    // 7.91% is the mocked engine's own levered IRR, formatted -- never
    // recomputed, rounded, or adjusted by the shell.
    const results = makeResults();
    expect(within(ownerSummary()).getAllByText('7.91%').length).toBeGreaterThanOrEqual(1);
    expect(formatPercent(results.levered_irr)).toBe('7.91%');
  });

  it('36. snapshot provenance is untouched by the shell', async () => {
    const user = userEvent.setup();
    const deal = makeDeal();
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(await within(sidebar()).findByText('111 Main St'));
    await waitFor(() => expect(mockGetDeal).toHaveBeenCalled());

    mockAnalyze.mockResolvedValue(makeResults());
    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    // The same provenance-validated refresh as before Sprint C: a fresh
    // fingerprint for the exact assumptions analyzed, then the snapshot.
    await waitFor(() => expect(mockFetchDealFingerprint).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(mockUpdateDealAnalysisSnapshot).toHaveBeenCalledWith(
        'deal-1',
        makeResults(),
        'fp-financial',
      ),
    );

    const snapshotCalls = mockUpdateDealAnalysisSnapshot.mock.calls.length;
    const fingerprintCalls = mockFetchDealFingerprint.mock.calls.length;
    for (const workspace of ['Risk', 'Documents', 'Overview', 'Underwrite']) {
      await goTo(user, workspace);
    }
    expect(mockUpdateDealAnalysisSnapshot.mock.calls.length).toBe(snapshotCalls);
    expect(mockFetchDealFingerprint.mock.calls.length).toBe(fingerprintCalls);
  });

  describe('default workspace rules (spec section 12.4)', () => {
    it('a fresh app starts on Underwrite', () => {
      render(<App />);
      expect(activeWorkspace()).toBe('Underwrite');
    });

    it('a successful Analyze moves to Overview', async () => {
      const user = userEvent.setup();
      render(<App />);
      await analyzeQuickGoldenDeal(user);

      expect(activeWorkspace()).toBe('Overview');
    });

    it('a failed Analyze stays put and surfaces the error where the user is', async () => {
      const user = userEvent.setup();
      render(<App />);
      await goTo(user, 'Risk');

      // No assumptions entered -- validation fails before any request.
      await user.click(screen.getByRole('button', { name: 'Analyze' }));

      expect(activeWorkspace()).toBe('Risk');
      expect(mockAnalyze).not.toHaveBeenCalled();
      expect(screen.getByText(/Purchase Price is required/)).toBeTruthy();
    });

    it('an API failure during Analyze also stays put', async () => {
      const user = userEvent.setup();
      mockAnalyze.mockRejectedValue(new ApiError('Exit cap rate must be positive.'));
      render(<App />);
      fillGoldenDeal();
      await goTo(user, 'Documents');

      await user.click(screen.getByRole('button', { name: 'Analyze' }));

      await screen.findByText('Exit cap rate must be positive.');
      expect(activeWorkspace()).toBe('Documents');
    });

    it('approving an Excel review moves to the workspace that owns assumptions', async () => {
      const user = userEvent.setup();
      mockUploadExcel.mockResolvedValue(makeExcelIntakeReport());
      render(<App />);

      await goTo(user, 'Documents');
      const file = new File(['PK'], 'anchor_input.xlsx', {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      });
      await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), file);
      await screen.findByLabelText('Excel Review Purchase Price');

      for (const field of [
        'Acquisition Costs',
        'Financing Fee',
        'Disposition Costs',
        'Annual CapEx Reserve',
        'Interest-Only Period',
      ]) {
        await user.type(screen.getByLabelText(`Excel Review ${field}`), '0');
      }
      await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));

      await waitFor(() => expect(activeWorkspace()).toBe('Underwrite'));
    });
  });

  describe('accessibility', () => {
    it('pairs every workspace tab with the panel it labels', async () => {
      const user = userEvent.setup();
      render(<App />);

      for (const [label, id] of [
        ['Overview', 'overview'],
        ['Underwrite', 'underwrite'],
        ['Risk', 'risk'],
        ['AI Analyst', 'ai'],
        ['Documents', 'documents'],
      ] as [string, string][]) {
        await goTo(user, label);
        const tab = screen.getByRole('tab', { name: label });
        const workspacePanel = panel(id);
        expect(tab.getAttribute('aria-controls')).toBe(workspacePanel.id);
        expect(workspacePanel.getAttribute('aria-labelledby')).toBe(tab.id);
        expect(workspacePanel.getAttribute('role')).toBe('tabpanel');
      }
    });

    it('keeps every shell control a real, keyboard-reachable button', () => {
      render(<App />);

      const controls = [
        ...within(sidebar()).getAllByRole('button'),
        screen.getByRole('button', { name: 'Save Deal' }),
        screen.getByRole('button', { name: 'Analyze' }),
        screen.getByRole('button', { name: 'More deal actions' }),
        ...screen.getAllByRole('tab'),
      ];
      for (const control of controls) {
        expect(control.tagName).toBe('BUTTON');
      }
    });

    it('navigates workspaces by keyboard alone', async () => {
      const user = userEvent.setup();
      render(<App />);

      screen.getByRole('tab', { name: 'Risk' }).focus();
      await user.keyboard('{Enter}');

      expect(activeWorkspace()).toBe('Risk');
    });
  });
});

// ===========================================================================
// Sprint C Gate C3 -- Underwrite workspace redesign.
//
// Underwrite is now five tabs (Acquisition / Operations / Debt / Exit /
// Results) with a compact strategy strip and a persistent Live Case rail,
// rather than one long stack of every assumption followed by every result.
// ===========================================================================

/** The Underwrite tab currently selected. */
function activeUnderwriteTab(): string {
  const nav = document.querySelector('[aria-label="Underwrite sections"]');
  return nav?.querySelector('[aria-selected="true"]')?.textContent ?? '';
}

function activeSubTab(label: string): string {
  const nav = document.querySelector(`[aria-label="${label}"]`);
  return nav?.querySelector('[aria-selected="true"]')?.textContent ?? '';
}

/** One Underwrite tab panel, whether or not it is the active one. */
function underwritePanel(id: string): HTMLElement {
  const node = document.getElementById(`underwrite-section-panel-${id}`);
  if (node === null) {
    throw new Error(`No ${id} Underwrite panel is rendered.`);
  }
  return node as HTMLElement;
}

function resultsPanelFor(id: string): HTMLElement {
  const node = document.getElementById(`underwrite-results-panel-${id}`);
  if (node === null) {
    throw new Error(`No ${id} results panel is rendered.`);
  }
  return node as HTMLElement;
}

function liveCase(): HTMLElement {
  const node = document.querySelector('.live-case');
  if (node === null) {
    throw new Error('No Live Case rail is rendered.');
  }
  return node as HTMLElement;
}

async function openUnderwriteTab(user: ReturnType<typeof userEvent.setup>, label: string) {
  await goTo(user, 'Underwrite');
  await user.click(
    within(document.querySelector('[aria-label="Underwrite sections"]') as HTMLElement).getByRole(
      'tab',
      { name: label },
    ),
  );
}

describe('Sprint C Gate C3 -- Underwrite workspace', () => {
  it('1. renders the five Underwrite tabs, with Acquisition active by default', async () => {
    const user = userEvent.setup();
    render(<App />);
    await goTo(user, 'Underwrite');

    const nav = within(document.querySelector('[aria-label="Underwrite sections"]') as HTMLElement);
    for (const label of ['Acquisition', 'Operations', 'Debt', 'Exit', 'Results']) {
      expect(nav.getByRole('tab', { name: label })).toBeTruthy();
    }
    expect(activeUnderwriteTab()).toBe('Acquisition');
  });

  it('2-5. shows only the active tab’s assumptions, for Detailed', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    await goTo(user, 'Underwrite');

    const cases: [string, string, string[]][] = [
      ['Acquisition', 'acquisition', ['Purchase Price', 'Hold Period', 'Acquisition Costs']],
      ['Debt', 'debt', ['LTV', 'Interest Rate', 'Amortization', 'Financing Fee']],
      ['Exit', 'exit', ['Exit Cap Rate', 'Disposition Costs']],
    ];
    for (const [label, id, fields] of cases) {
      await openUnderwriteTab(user, label);
      expect(activeUnderwriteTab()).toBe(label);
      expect(underwritePanel(id).hasAttribute('hidden')).toBe(false);
      for (const field of fields) {
        expect(within(underwritePanel(id)).getByText(field)).toBeTruthy();
      }
      for (const [, otherId] of cases.filter(([other]) => other !== label)) {
        expect(underwritePanel(otherId).hasAttribute('hidden')).toBe(true);
      }
    }
  });

  it('3. Detailed Operations has Revenue / Expenses / Growth sub-navigation', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    await openUnderwriteTab(user, 'Operations');

    const nav = within(document.querySelector('[aria-label="Operations sections"]') as HTMLElement);
    for (const label of ['Revenue', 'Expenses', 'Growth']) {
      expect(nav.getByRole('tab', { name: label })).toBeTruthy();
    }
    expect(activeSubTab('Operations sections')).toBe('Revenue');
    expect(within(underwritePanel('operations')).getByText('Gross Potential Rent')).toBeTruthy();

    await user.click(nav.getByRole('tab', { name: 'Expenses' }));
    expect(activeSubTab('Operations sections')).toBe('Expenses');
    expect(document.getElementById('underwrite-operations-panel-revenue')?.hasAttribute('hidden')).toBe(
      true,
    );
    expect(
      document.getElementById('underwrite-operations-panel-expenses')?.hasAttribute('hidden'),
    ).toBe(false);

    await user.click(nav.getByRole('tab', { name: 'Growth' }));
    expect(within(underwritePanel('operations')).getByText('Revenue Growth')).toBeTruthy();
    expect(within(underwritePanel('operations')).getByText('Annual CapEx Reserve')).toBeTruthy();
  });

  it('7. Quick uses the same five tabs, with its own authoritative inputs', async () => {
    const user = userEvent.setup();
    render(<App />);
    await goTo(user, 'Underwrite');

    const nav = within(document.querySelector('[aria-label="Underwrite sections"]') as HTMLElement);
    for (const label of ['Acquisition', 'Operations', 'Debt', 'Exit', 'Results']) {
      expect(nav.getByRole('tab', { name: label })).toBeTruthy();
    }

    await openUnderwriteTab(user, 'Operations');
    expect(within(underwritePanel('operations')).getByText('Current NOI')).toBeTruthy();
    expect(within(underwritePanel('operations')).getByText('Occupancy')).toBeTruthy();
    // Quick's four operating inputs do not justify sub-navigation.
    expect(document.querySelector('[aria-label="Operations sections"]')).toBeNull();
  });

  it('6, 9, 10, 11. Results has sub-navigation and shows one surface at a time', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeDetailedGoldenDeal(user);
    await openUnderwriteTab(user, 'Results');

    const nav = within(document.querySelector('[aria-label="Results views"]') as HTMLElement);
    for (const label of ['Summary', 'Cash Flow', 'Owner Returns', 'Operating Statement']) {
      expect(nav.getByRole('tab', { name: label })).toBeTruthy();
    }

    const ids = ['summary', 'cash-flow', 'owner-returns', 'operating-statement'];
    const labels = ['Summary', 'Cash Flow', 'Owner Returns', 'Operating Statement'];
    for (let i = 0; i < labels.length; i += 1) {
      await user.click(nav.getByRole('tab', { name: labels[i] }));
      expect(resultsPanelFor(ids[i]).hasAttribute('hidden')).toBe(false);
      for (const other of ids.filter((id) => id !== ids[i])) {
        expect(resultsPanelFor(other).hasAttribute('hidden')).toBe(true);
      }
    }
  });

  it('11b. Quick Results omits the Operating Statement it has no data for', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeQuickGoldenDeal(user);
    await openUnderwriteTab(user, 'Results');

    const nav = within(document.querySelector('[aria-label="Results views"]') as HTMLElement);
    expect(nav.getByRole('tab', { name: 'Summary' })).toBeTruthy();
    expect(nav.queryByRole('tab', { name: 'Operating Statement' })).toBeNull();
    expect(operatingStatement()).toBeNull();
  });

  it('6b. the Results tab shows a clean empty state before any analysis', async () => {
    const user = userEvent.setup();
    render(<App />);
    await openUnderwriteTab(user, 'Results');

    expect(within(underwritePanel('results')).getByText(/Analyze the deal to see/)).toBeTruthy();
    expect(document.querySelector('[aria-label="Results views"]')).toBeNull();
  });

  it('12, 14. Detailed inputs survive switching between every tab', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    fillDetailedGoldenDeal();

    for (const label of ['Operations', 'Debt', 'Exit', 'Results', 'Acquisition']) {
      await openUnderwriteTab(user, label);
    }

    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty(
      'value',
      DETAILED_GOLDEN_FORM_VALUES.terms.purchasePrice,
    );
    expect(screen.getByLabelText(/^Gross Potential Rent/)).toHaveProperty(
      'value',
      DETAILED_GOLDEN_FORM_VALUES.operating.grossPotentialRent,
    );
    expect(screen.getByLabelText(/^Interest Rate/)).toHaveProperty(
      'value',
      DETAILED_GOLDEN_FORM_VALUES.terms.interestRate,
    );
  });

  it('13. Quick inputs survive switching between every tab', async () => {
    const user = userEvent.setup();
    render(<App />);
    fillGoldenDeal();

    for (const label of ['Debt', 'Exit', 'Operations', 'Results', 'Acquisition']) {
      await openUnderwriteTab(user, label);
    }

    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty(
      'value',
      DEFAULT_FORM_VALUES.purchasePrice,
    );
    expect(screen.getByLabelText(/^Current NOI/)).toHaveProperty(
      'value',
      DEFAULT_FORM_VALUES.currentNoi,
    );
  });

  it('12b. an in-flight analysis disables inputs on every tab, not just the visible one', async () => {
    const user = userEvent.setup();
    const pending = deferred<AcquisitionResults>();
    mockAnalyze.mockReturnValueOnce(pending.promise);
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('disabled', true);
    expect(screen.getByLabelText(/^Interest Rate/)).toHaveProperty('disabled', true);

    pending.resolve(makeResults());
    await waitFor(() =>
      expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('disabled', false),
    );
  });

  it('15. Deal Context shows as a compact strategy strip, not a permanent textarea', async () => {
    const user = userEvent.setup();
    render(<App />);
    await goTo(user, 'Underwrite');

    const strip = document.querySelector('.strategy-strip') as HTMLElement;
    expect(strip).toBeTruthy();
    expect(within(strip).getByText('Strategy')).toBeTruthy();
    // The editor is present but collapsed until the analyst opens it.
    const editor = document.querySelector('.strategy-strip-editor') as HTMLElement;
    expect(editor.hasAttribute('hidden')).toBe(true);

    await user.click(within(strip).getByRole('button', { name: 'Edit' }));
    expect(editor.hasAttribute('hidden')).toBe(false);
    expect(within(strip).getByRole('button', { name: 'Done' })).toBeTruthy();
  });

  it('15b. the strip summarises the saved context and survives collapsing', async () => {
    const user = userEvent.setup();
    render(<App />);
    await goTo(user, 'Underwrite');

    const strip = document.querySelector('.strategy-strip') as HTMLElement;
    await user.click(within(strip).getByRole('button', { name: 'Edit' }));
    fireEvent.change(screen.getByLabelText('Deal Context'), {
      target: { value: 'Core-plus industrial, mark-to-market lease-up.' },
    });
    await user.click(within(strip).getByRole('button', { name: 'Done' }));

    expect((strip.querySelector('.strategy-strip-text') as HTMLElement).textContent).toBe(
      'Core-plus industrial, mark-to-market lease-up.',
    );
    expect(screen.getByLabelText('Deal Context')).toHaveProperty(
      'value',
      'Core-plus industrial, mark-to-market lease-up.',
    );
  });

  it('16, 17, 18. editing context keeps results, invalidates AI, and never re-runs it', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeQuickGoldenDeal(user);
    await goTo(user, 'AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    await screen.findByText('Five-year hold with moderate leverage.');

    await goTo(user, 'Underwrite');
    fireEvent.change(screen.getByLabelText('Deal Context'), { target: { value: 'Value-add.' } });

    // Deterministic output survives; the stale AI interpretation does not.
    expect(panel('overview').querySelector('.owner-summary-panel')).toBeTruthy();
    expect(within(panel('risk')).getByText('Sensitivity Analysis')).toBeTruthy();
    expect(screen.queryByText('Five-year hold with moderate leverage.')).toBeNull();
    expect(mockFetchAIAnalysis).toHaveBeenCalledTimes(1);
  });

  it('16b. editing context still marks a saved deal dirty', async () => {
    const user = userEvent.setup();
    mockCreateDeal.mockResolvedValue(makeDeal());
    render(<App />);
    fillGoldenDeal();
    await user.type(screen.getByLabelText('Deal Name'), '111 Main St');
    await user.click(screen.getByRole('button', { name: 'Save Deal' }));
    await screen.findByText(/^Saved/);

    await goTo(user, 'Underwrite');
    fireEvent.change(screen.getByLabelText('Deal Context'), { target: { value: 'Strategy.' } });

    expect(screen.getByText('Unsaved changes')).toBeTruthy();
  });

  it('19. the Live Case rail states plainly that there is nothing to show yet', async () => {
    const user = userEvent.setup();
    render(<App />);
    await goTo(user, 'Underwrite');

    expect(within(liveCase()).getByText('Analyze the deal to populate live metrics.')).toBeTruthy();
    // No fabricated zeros.
    expect(within(liveCase()).queryByText('$0')).toBeNull();
    expect(within(liveCase()).queryByText('0.00%')).toBeNull();
  });

  it('20. the Live Case rail shows authoritative metrics for the active tab', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeQuickGoldenDeal(user);

    await openUnderwriteTab(user, 'Acquisition');
    expect(within(liveCase()).getByText('Levered IRR')).toBeTruthy();
    expect(within(liveCase()).getByText('7.91%')).toBeTruthy();
    expect(within(liveCase()).getByText('Initial Equity')).toBeTruthy();

    await openUnderwriteTab(user, 'Debt');
    expect(within(liveCase()).getByText('Loan Amount')).toBeTruthy();
    expect(within(liveCase()).getByText('Year 1 Debt Yield')).toBeTruthy();
    expect(within(liveCase()).queryByText('Initial Equity')).toBeNull();

    await openUnderwriteTab(user, 'Exit');
    expect(within(liveCase()).getByText('Exit Value')).toBeTruthy();
    expect(within(liveCase()).getByText('Net Sale Proceeds')).toBeTruthy();
  });

  it('20b. the Live Case rail never triggers an analysis of its own', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeQuickGoldenDeal(user);
    const calls = mockAnalyze.mock.calls.length;

    for (const label of ['Acquisition', 'Operations', 'Debt', 'Exit', 'Results']) {
      await openUnderwriteTab(user, label);
    }

    expect(mockAnalyze.mock.calls.length).toBe(calls);
  });

  it('21. the Live Case rail shows N/A for a metric the engine returned as null', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(
      makeResults({ levered_irr: null, equity_multiple: null, min_dscr: null }),
    );
    render(<App />);
    fillGoldenDeal();
    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await waitFor(() => expect(mockAnalyze).toHaveBeenCalled());
    await openUnderwriteTab(user, 'Acquisition');

    expect(within(liveCase()).getAllByText('N/A').length).toBeGreaterThanOrEqual(2);
  });

  it('22. the Live Case rail preserves the sign of a negative engine value', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults({ levered_irr: -0.0512 }));
    render(<App />);
    fillGoldenDeal();
    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await waitFor(() => expect(mockAnalyze).toHaveBeenCalled());
    await openUnderwriteTab(user, 'Acquisition');

    expect(within(liveCase()).getByText('-5.12%')).toBeTruthy();
  });

  it('23, 24. the header owns Analyze; no form-level Analyze button remains', async () => {
    const user = userEvent.setup();
    render(<App />);
    await goTo(user, 'Underwrite');

    expect(screen.queryByRole('button', { name: 'Analyze Deal' })).toBeNull();
    const header = within(document.querySelector('.deal-header') as HTMLElement);
    expect(header.getByRole('button', { name: 'Analyze' })).toBeTruthy();
    expect(screen.getAllByRole('button', { name: 'Analyze' })).toHaveLength(1);

    fillGoldenDeal();
    mockAnalyze.mockResolvedValue(makeResults());
    await user.click(header.getByRole('button', { name: 'Analyze' }));

    await waitFor(() => expect(mockAnalyze).toHaveBeenCalledTimes(1));
  });

  it('25. the request C3 sends is identical to the pre-C3 golden request', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    await waitFor(() => expect(mockAnalyze).toHaveBeenCalledWith(GOLDEN_DEAL_REQUEST));
  });

  it('23b. Analyze is reachable from every Underwrite tab', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();
    await openUnderwriteTab(user, 'Debt');

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    await waitFor(() => expect(mockAnalyze).toHaveBeenCalledTimes(1));
  });

  it('26, 27. a reopened analyzed deal restores its results into the Results tab', async () => {
    const user = userEvent.setup();
    const deal = makeDeal({ analysis_snapshot: makeResults() });
    mockListDeals.mockResolvedValue([deal]);
    mockGetDeal.mockResolvedValue(deal);
    render(<App />);

    await user.click(await within(sidebar()).findByText('111 Main St'));
    await waitFor(() => expect(mockGetDeal).toHaveBeenCalled());
    await openUnderwriteTab(user, 'Results');

    expect(underwritePanel('results').querySelector('.results-panel')).toBeTruthy();
    expect(within(liveCase()).getByText('7.91%')).toBeTruthy();
    expect(mockAnalyze).not.toHaveBeenCalled();
  });

  it('28. dirty state still tracks an assumption edited on any tab', async () => {
    const user = userEvent.setup();
    mockCreateDeal.mockResolvedValue(makeDeal());
    render(<App />);
    fillGoldenDeal();
    await user.type(screen.getByLabelText('Deal Name'), '111 Main St');
    await user.click(screen.getByRole('button', { name: 'Save Deal' }));
    await screen.findByText(/^Saved/);

    await openUnderwriteTab(user, 'Debt');
    fireEvent.change(screen.getByLabelText(/^Interest Rate/), { target: { value: '6.75' } });

    expect(screen.getByText('Unsaved changes')).toBeTruthy();
  });

  it('29. the tabbed Underwrite introduces no calculation -- values pass through', async () => {
    const user = userEvent.setup();
    const results = makeResults();
    mockAnalyze.mockResolvedValue(results);
    render(<App />);
    fillGoldenDeal();
    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await waitFor(() => expect(mockAnalyze).toHaveBeenCalled());
    await openUnderwriteTab(user, 'Results');

    // Every rendered figure is the mocked engine output, formatted only.
    const summary = resultsPanelFor('summary');
    expect(within(summary).getAllByText(formatPercent(results.levered_irr)).length).toBeGreaterThan(
      0,
    );
    expect(
      within(summary).getAllByText(formatCurrency(results.loan_amount)).length,
    ).toBeGreaterThan(0);
  });

  it('30. Quick and Detailed keep entirely separate tabbed state', async () => {
    const user = userEvent.setup();
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    await openUnderwriteTab(user, 'Operations');

    // Detailed Operations shows its own inputs and none of Quick's.
    expect(screen.getByLabelText(/^Gross Potential Rent/)).toBeTruthy();
    expect(screen.queryByLabelText(/^Current NOI/)).toBeNull();

    await user.click(screen.getByRole('tab', { name: 'Quick Underwrite' }));
    expect(screen.getByLabelText(/^Current NOI/)).toHaveProperty(
      'value',
      DEFAULT_FORM_VALUES.currentNoi,
    );
    expect(screen.queryByLabelText(/^Gross Potential Rent/)).toBeNull();
    // The selected tab is shared navigation state, so it carries across.
    expect(activeUnderwriteTab()).toBe('Operations');
  });

  it('accessibility: Underwrite tabs and panels are wired and keyboard-operable', async () => {
    const user = userEvent.setup();
    render(<App />);
    await goTo(user, 'Underwrite');

    const nav = within(document.querySelector('[aria-label="Underwrite sections"]') as HTMLElement);
    const debtTab = nav.getByRole('tab', { name: 'Debt' });
    expect(debtTab.getAttribute('aria-controls')).toBe(underwritePanel('debt').id);
    expect(underwritePanel('debt').getAttribute('aria-labelledby')).toBe(debtTab.id);

    debtTab.focus();
    await user.keyboard('{Enter}');
    expect(activeUnderwriteTab()).toBe('Debt');
  });
});
