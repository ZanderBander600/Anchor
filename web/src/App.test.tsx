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
  fetchDetailedAIAnalysis,
  fetchDetailedBreakEvenAnalysis,
  fetchDetailedSensitivityPresets,
  fetchSensitivityPresets,
  getDeal,
  listDeals,
  updateDeal,
  updateDetailedDeal,
  uploadDetailedExcel,
  uploadDetailedOm,
  uploadExcel,
  uploadOm,
} from './api';
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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    expect(await screen.findByText('Interest-Only Period is required.')).toBeTruthy();
    expect(mockAnalyze).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText(/^Interest-Only Period/), '2');
    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    expect(await screen.findByText(/Purchase Price is required/)).toBeTruthy();
    expect(mockAnalyze).not.toHaveBeenCalled();
  });

  it('shows key results after a successful analysis', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    expect(await screen.findByText('7.91%')).toBeTruthy();
    expect(screen.getByText('1.44x')).toBeTruthy();
  });

  it('renders the V2 golden case: transaction costs, CapEx, and Year 1 vs. Minimum DSCR distinctly (Gate 6)', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeV2GoldenResults());
    render(<App />);
    fillV2GoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    expect(await screen.findByText('7.38%')).toBeTruthy(); // Levered IRR
    expect(screen.getByText('1.38x')).toBeTruthy(); // Equity Multiple
    expect(screen.getByText('$200,000')).toBeTruthy(); // Acquisition Costs
    expect(screen.getByText('$60,000')).toBeTruthy(); // Financing Fee
    expect(screen.getByText('$267,525')).toBeTruthy(); // Disposition Costs

    // Year 1 DSCR (headline strip) and Minimum DSCR render as visibly
    // distinct values -- never computed in the frontend, only rendered.
    expect(screen.getAllByText('2.00x').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Min 1.65x')).toBeTruthy();
  });

  it('shows the Owner Returns headline (Year 1 Levered CoC, Year 1 Debt Yield, Cumulative Operating Distributions) in Quick mode', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeV2GoldenResults());
    render(<App />);
    fillV2GoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    expect(await screen.findByText('Owner Returns')).toBeTruthy();
    expect(screen.getByText('Year 1 Levered CoC')).toBeTruthy();
    // "5.87%"/"10.00%" appear both in the headline card and in the Owner
    // Return Schedule's Year 1 row -- assert at least one match rather
    // than assuming a single occurrence.
    expect(screen.getAllByText('5.87%').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Year 1 Debt Yield')).toBeTruthy();
    expect(screen.getAllByText('10.00%').length).toBeGreaterThanOrEqual(1);
    // "Cumulative Operating Distributions" labels both the headline card
    // and the schedule table's column header -- assert at least one match
    // rather than assuming uniqueness.
    expect(
      screen.getAllByText('Cumulative Operating Distributions').length,
    ).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('$1,175,947').length).toBeGreaterThanOrEqual(1);
  });

  it('shows the annual CapEx series in the year-by-year table', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeV2GoldenResults());
    render(<App />);
    fillV2GoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    await screen.findByText('7.38%');

    expect(screen.getAllByText('$50,000').length).toBeGreaterThanOrEqual(1);
  });

  it('clears displayed results when an assumption is edited after a successful analysis', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    expect(await screen.findByText('7.91%')).toBeTruthy();

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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    expect(await screen.findByText('7.91%')).toBeTruthy();

    const second = deferred<AcquisitionResults>();
    mockAnalyze.mockReturnValueOnce(second.promise);

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    expect(screen.queryByText('7.91%')).toBeNull();

    second.resolve(makeResults({ levered_irr: 0.09 }));
    expect(await screen.findByText('9.00%')).toBeTruthy();
  });

  it('does not display stale results and shows an error banner after a failed analysis', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValueOnce(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    expect(await screen.findByText('7.91%')).toBeTruthy();

    mockAnalyze.mockRejectedValueOnce(new ApiError('The backend rejected the request.'));

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    expect(await screen.findByText('The backend rejected the request.')).toBeTruthy();
    expect(screen.queryByText('7.91%')).toBeNull();
  });

  it('disables inputs and the Analyze button while a request is pending', async () => {
    const user = userEvent.setup();
    const pending = deferred<AcquisitionResults>();
    mockAnalyze.mockReturnValueOnce(pending.promise);
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('disabled', true);
    expect(screen.getByRole('button', { name: 'Analyzing…' })).toHaveProperty('disabled', true);

    pending.resolve(makeResults());
    await screen.findByRole('button', { name: 'Analyze Deal' });

    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('disabled', false);
    expect(screen.getByRole('button', { name: 'Analyze Deal' })).toHaveProperty('disabled', false);
  });

  it('replaces the first result with the second successful analysis', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValueOnce(makeResults({ levered_irr: 0.0791303 }));
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    expect(await screen.findByText('7.91%')).toBeTruthy();

    mockAnalyze.mockResolvedValueOnce(makeResults({ levered_irr: 0.12 }));
    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    expect(await screen.findByText('12.00%')).toBeTruthy();
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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    expect(await screen.findByText('Sensitivity Analysis')).toBeTruthy();
    expect(mockFetchSensitivityPresets).toHaveBeenCalledTimes(1);
  });

  it('passes the same raw-decimal request to sensitivity as to the base analysis', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    await screen.findByText('Sensitivity Analysis');

    expect(mockFetchSensitivityPresets).toHaveBeenCalledWith(mockAnalyze.mock.calls[0][0]);
  });

  it('clears sensitivity results when an assumption is edited after a successful analysis', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    expect(await screen.findByText('The sensitivity request failed.')).toBeTruthy();
    expect(screen.getByText('7.91%')).toBeTruthy();
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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    expect(await screen.findByText('Break-Even Analysis')).toBeTruthy();
    expect(mockFetchBreakEvenAnalysis).toHaveBeenCalledTimes(1);
  });

  it('renders default hurdle controls and all five result cards', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    await screen.findByText('Break-Even Analysis');
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

    expect(await screen.findByText('$44,120,000')).toBeTruthy();
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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    expect(await screen.findByText('Not found in tested range')).toBeTruthy();
    expect(screen.queryByText(/impossible/i)).toBeNull();
    expect(screen.queryByText(/no solution exists/i)).toBeNull();
  });

  it('clears break-even results when a base assumption is edited', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    expect(await screen.findByText('The break-even request failed.')).toBeTruthy();
    expect(screen.getByText('7.91%')).toBeTruthy();
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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    expect(await screen.findByText('Anchor AI Analyst')).toBeTruthy();
    expect(mockFetchAIAnalysis).not.toHaveBeenCalled();
  });

  it('does not auto-generate an AI analysis after the base analysis completes', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    await screen.findByText('Anchor AI Analyst');
    await screen.findByText('Break-Even Analysis');

    expect(mockFetchAIAnalysis).not.toHaveBeenCalled();
  });

  it('generates an AI analysis only when the Generate button is clicked', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    await screen.findByText('Anchor AI Analyst');

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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    await screen.findByText('Anchor AI Analyst');

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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    await screen.findByText('Anchor AI Analyst');
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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    await screen.findByText('Anchor AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));

    expect(await screen.findByText('OPENAI_API_KEY is not configured.')).toBeTruthy();
    expect(screen.getByText('7.91%')).toBeTruthy();
    expect(screen.getByText('Break-Even Analysis')).toBeTruthy();
    expect(screen.getByText('Sensitivity Analysis')).toBeTruthy();
  });

  it('clears AI output when a base assumption is edited', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    await screen.findByText('Anchor AI Analyst');
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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    await screen.findByText('Anchor AI Analyst');
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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    await screen.findByText('Anchor AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    expect(await screen.findByText('First view.')).toBeTruthy();

    mockFetchAIAnalysis.mockResolvedValueOnce(
      makeAiAnalysis({ investment_view: 'Second view.' }),
    );
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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    await screen.findByText('Anchor AI Analyst');
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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    expect(await screen.findByText('7.91%')).toBeTruthy();

    mockUploadOm.mockResolvedValue(makeExtractionResult());
    const file = new File(['%PDF-1.4'], 'om.pdf', { type: 'application/pdf' });
    await user.upload(screen.getByLabelText('Upload OM (PDF)'), file);
    await screen.findByRole('heading', { name: 'Purchase Price' });

    const purchasePriceCard = screen.getByRole('heading', { name: 'Purchase Price' }).closest('.om-field-card') as HTMLElement;
    await user.click(
      Array.from(purchasePriceCard.querySelectorAll('button')).find((b) => b.textContent === 'Approve')!,
    );
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

    await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));
    expect(await screen.findByText('Acquisition Costs is required.')).toBeTruthy();
    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty(
      'value',
      BLANK_FORM_VALUES.purchasePrice,
    );

    await completeBlankedV2ReviewFields(user);
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
    await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));
    await waitFor(() => {
      expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '48000000');
    });

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    await waitFor(() => expect(mockAnalyze).toHaveBeenCalledTimes(1));
    expect(mockAnalyze).toHaveBeenCalledWith(makeAcquisitionRequest());
  });

  it('Cancel Review discards the pending review and leaves active assumptions unchanged', async () => {
    const user = userEvent.setup();
    await uploadWorkbook(user);

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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    expect(await screen.findByText('7.91%')).toBeTruthy();

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
    expect(screen.getByText('7.91%')).toBeTruthy();

    await completeBlankedV2ReviewFields(user);
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

  it('scrolls the assumptions form into view after approval, not after upload', async () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;

    const user = userEvent.setup();
    await uploadWorkbook(user);
    expect(scrollIntoView).not.toHaveBeenCalled();

    await completeBlankedV2ReviewFields(user);
    await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));

    await waitFor(() => {
      expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' });
    });
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

    expect(await screen.findByText('Deal A')).toBeTruthy();
    expect(screen.getByText('Deal B')).toBeTruthy();
    expect(mockListDeals).toHaveBeenCalledTimes(1);
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
    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    expect(await screen.findByText('7.91%')).toBeTruthy();

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
    expect(await screen.findByText('111 Main St')).toBeTruthy();
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
      mockListDeals.mockResolvedValueOnce([original]).mockResolvedValueOnce([original, copy]);
      mockDuplicateDeal.mockResolvedValue(copy);
      render(<App />);

      await user.click(screen.getByRole('button', { name: 'Deal Library' }));
      await screen.findByText('111 Main St');
      await user.click(screen.getByRole('button', { name: 'Duplicate' }));

      await waitFor(() => expect(mockDuplicateDeal).toHaveBeenCalledWith('deal-1'));
      expect(await screen.findByText('111 Main St (Copy)')).toBeTruthy();
      expect(mockListDeals).toHaveBeenCalledTimes(2);
    });

    it('a duplicated deal, once opened, shows all five V2 assumptions exactly as the original', async () => {
      const user = userEvent.setup();
      const original = makeDeal({ inputs: buildAcquisitionRequest(V2_GOLDEN_FORM_VALUES) });
      const copy = makeDeal({ id: 'deal-2', name: '111 Main St (Copy)', inputs: original.inputs });
      mockListDeals.mockResolvedValueOnce([original]).mockResolvedValueOnce([original, copy]);
      mockDuplicateDeal.mockResolvedValue(copy);
      mockGetDeal.mockResolvedValue(copy);
      render(<App />);

      await user.click(screen.getByRole('button', { name: 'Deal Library' }));
      await screen.findByText('111 Main St');
      await user.click(screen.getByRole('button', { name: 'Duplicate' }));
      await screen.findByText('111 Main St (Copy)');

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
      expect(screen.getByText('111 Main St')).toBeTruthy();
    });

    it('confirmed deletion removes the deal and refreshes the library', async () => {
      const user = userEvent.setup();
      mockListDeals.mockResolvedValueOnce([makeDeal()]).mockResolvedValueOnce([]);
      render(<App />);

      await user.click(screen.getByRole('button', { name: 'Deal Library' }));
      await screen.findByText('111 Main St');
      await user.click(screen.getByRole('button', { name: 'Delete' }));

      await waitFor(() => expect(mockDeleteDeal).toHaveBeenCalledWith('deal-1'));
      expect(await screen.findByText(/No saved deals yet/)).toBeTruthy();
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
      await user.click(screen.getByRole('button', { name: 'Cancel Review' }));

      expect(screen.queryByLabelText('Excel Review Purchase Price')).toBeNull();
      expect(screen.getByText(/^Saved/)).toBeTruthy();
      expect(screen.queryByText('Unsaved changes')).toBeNull();
    });

    it('OM-approved data is unsaved until saved', async () => {
      const user = userEvent.setup();
      mockUploadOm.mockResolvedValue(makeExtractionResult());
      render(<App />);

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

      await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
      await screen.findByText('7.91%');

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

      await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
      await screen.findByText('7.91%');

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
    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

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

    expect(await screen.findByText('Operating Statement')).toBeTruthy();
    expect(screen.getByText('Key Returns')).toBeTruthy();
    expect(screen.getAllByText('$600,000').length).toBeGreaterThan(0);
  });

  it('shows the Owner Returns headline in Detailed mode, identical to Quick for equivalent economics', async () => {
    const user = userEvent.setup();
    mockAnalyzeDetailed.mockResolvedValue(makeDetailedResults());
    render(<App />);

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    fillDetailedGoldenDeal();
    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    expect(await screen.findByText('Owner Returns')).toBeTruthy();
    expect(screen.getByText('Year 1 Levered CoC')).toBeTruthy();
    expect(screen.getAllByText('5.87%').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Year 1 Debt Yield')).toBeTruthy();
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
    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

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
    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

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
  await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
  await screen.findByText('Operating Statement');
}

describe('AI Analyst in Detailed mode (Gate 9)', () => {
  it('AI Analyst works in Quick mode (regression)', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();
    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    await screen.findByText('Key Returns');

    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));

    await waitFor(() => expect(mockFetchAIAnalysis).toHaveBeenCalledTimes(1));
    expect(mockFetchDetailedAIAnalysis).not.toHaveBeenCalled();
    expect(await screen.findByText('Five-year hold with moderate leverage.')).toBeTruthy();
  });

  it('AI Analyst works in Detailed mode', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeDetailedGoldenDeal(user);

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
    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    await screen.findByText('Key Returns');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    await waitFor(() => expect(mockFetchAIAnalysis).toHaveBeenCalledTimes(1));
    const [quickInputsArg] = mockFetchAIAnalysis.mock.calls[0];
    expect(quickInputsArg).toHaveProperty('current_noi');
    expect(quickInputsArg).toHaveProperty('noi_growth');

    // Now switch to Detailed and generate again.
    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));
    await analyzeDetailedGoldenDeal(user);
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

    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));

    expect(await screen.findByText('The AI Analyst is not configured.')).toBeTruthy();
  });

  it('clears the Detailed AI analysis when a Detailed assumption is edited', async () => {
    const user = userEvent.setup();
    render(<App />);
    await analyzeDetailedGoldenDeal(user);
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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    await waitFor(() => expect(mockFetchSensitivityPresets).toHaveBeenCalledTimes(1));
    expect(mockFetchDetailedSensitivityPresets).not.toHaveBeenCalled();
    expect(mockFetchSensitivityPresets).toHaveBeenCalledWith(mockAnalyze.mock.calls[0][0]);
    // Quick's own preset bundle still has its exit_cap_noi_growth tab.
    expect(await screen.findByRole('tab', { name: 'Exit Cap × NOI Growth' })).toBeTruthy();
  });

  it('6. Quick break-even remains unchanged (regression)', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

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
    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
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
    expect(screen.getByText('$9,487,500')).toBeTruthy();
    expect(screen.getByText('7.10%')).toBeTruthy();
    expect(screen.getByText('7.12%')).toBeTruthy();
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

    expect(await screen.findByText('$12,345,678')).toBeTruthy();
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

    await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));

    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '10000000');
    expect(screen.getByLabelText(/^Gross Potential Rent/)).toHaveProperty('value', '800000');
    expect(screen.getByLabelText(/^Interest-Only Period/)).toHaveProperty('value', '2');
    expect(screen.getByLabelText(/^Expense Growth/)).toHaveProperty('value', '3');
  });

  it('Approve & Load Assumptions never automatically calls Analyze', async () => {
    const user = userEvent.setup();
    await uploadDetailedWorkbook(user);

    await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));

    expect(mockAnalyzeDetailed).not.toHaveBeenCalled();
  });

  it('Cancel Review discards the pending review and leaves active Detailed assumptions unchanged', async () => {
    const user = userEvent.setup();
    await uploadDetailedWorkbook(user);

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

    await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));
    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

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

    expect(await screen.findByText('Golden Detailed Deal')).toBeTruthy();
    expect(screen.getByText('Detailed')).toBeTruthy();
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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
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
    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    await waitFor(() => expect(mockAnalyzeDetailed).toHaveBeenCalledTimes(1));

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
    await screen.findByText('Golden Detailed Deal');
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
    await screen.findByText('Golden Detailed Deal');
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
    const quickRow = (await screen.findByText(quickDeal.name)).closest('li');
    if (!quickRow) throw new Error('Quick deal row not found');
    await user.click(within(quickRow).getByRole('button', { name: 'Open' }));
    await screen.findByText(/^Saved/);
    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    await waitFor(() => expect(mockAnalyze).toHaveBeenCalledTimes(1));
    expect(screen.getByText('Key Returns')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    const detailedRow = (await screen.findByText(detailedDeal.name)).closest('li');
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
    const detailedRow = (await screen.findByText(detailedDeal.name)).closest('li');
    if (!detailedRow) throw new Error('Detailed deal row not found');
    await user.click(within(detailedRow).getByRole('button', { name: 'Open' }));
    await screen.findByText(/^Saved/);
    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    await waitFor(() => expect(mockAnalyzeDetailed).toHaveBeenCalledTimes(1));
    expect(screen.getByText('Operating Statement')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    const quickRow = (await screen.findByText(quickDeal.name)).closest('li');
    if (!quickRow) throw new Error('Quick deal row not found');
    await user.click(within(quickRow).getByRole('button', { name: 'Open' }));

    expect(screen.getByRole('tab', { name: 'Quick Underwrite' })).toHaveProperty(
      'ariaSelected',
      'true',
    );
    expect(screen.queryByText('Operating Statement')).toBeNull();
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
    await user.click(screen.getByRole('button', { name: 'Use approved values' }));

    expect(screen.getByLabelText(/^Property Taxes/)).toHaveProperty('value', '0');
  });

  it('Approve never automatically calls Analyze', async () => {
    const user = userEvent.setup();
    await uploadDetailedOm(user);

    await user.click(
      within(omFieldCard('Purchase Price')).getByRole('button', { name: 'Approve' }),
    );
    await user.click(screen.getByRole('button', { name: 'Use approved values' }));

    expect(mockAnalyzeDetailed).not.toHaveBeenCalled();
  });

  it('Cancel Review leaves active Detailed assumptions unchanged', async () => {
    const user = userEvent.setup();
    await uploadDetailedOm(user);

    await user.click(
      within(omFieldCard('Purchase Price')).getByRole('button', { name: 'Approve' }),
    );
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

    const file = new File(['%PDF-1.4'], 'om.pdf', { type: 'application/pdf' });
    await user.upload(screen.getByLabelText('Upload OM (PDF)'), file);
    await waitFor(() => {
      expect(screen.getByText('Purchase Price: $12,000,000', { exact: false })).toBeTruthy();
    });

    const card = screen.getByRole('heading', { name: 'Purchase Price' }).closest('.om-field-card');
    if (!card) throw new Error('Purchase Price card not found');
    await user.click(within(card as HTMLElement).getByRole('button', { name: 'Approve' }));
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
    expect(mockCreateDeal).toHaveBeenCalledWith(
      '111 Main St',
      GOLDEN_DEAL_REQUEST,
      'Value-add play.',
    );
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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    expect(await screen.findByText('Key Returns')).toBeTruthy();

    fireEvent.change(screen.getByLabelText('Deal Context'), {
      target: { value: 'Prioritize income over IRR.' },
    });

    expect(screen.getByText('Key Returns')).toBeTruthy();
    expect(screen.getByText('Owner Returns')).toBeTruthy();
  });

  it('editing Deal Context after generating AI analysis clears the stale AI output', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);
    fillGoldenDeal();

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    await screen.findByText('Anchor AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    expect(await screen.findByText('Investment View')).toBeTruthy();

    fireEvent.change(screen.getByLabelText('Deal Context'), {
      target: { value: 'Now a refinance-and-hold strategy.' },
    });

    expect(screen.queryByText('Investment View')).toBeNull();
    expect(screen.getByRole('button', { name: 'Generate AI Analysis' })).toBeTruthy();
    // Deterministic results remain -- only the stale AI output was cleared.
    expect(screen.getByText('Key Returns')).toBeTruthy();
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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    await screen.findByText('Key Returns');

    expect(screen.getByLabelText('Deal Context')).toHaveProperty(
      'value',
      'Strategy typed before analyzing.',
    );
  });
});
