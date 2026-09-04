import { describe, expect, it } from 'vitest';
import { buildOwnerSummaryData } from './ownerSummary';
import type { OwnerSummarySource } from './ownerSummary';
import type {
  AcquisitionRequest,
  AcquisitionResults,
  AcquisitionTermsRequest,
  DetailedOperatingInputsRequest,
  StandardBreakEvenAnalysis,
  StandardDetailedBreakEvenAnalysis,
} from './types';
// Vite's `?raw` suffix loads the module's own source text as a plain string
// -- used only by the architecture guardrail below to scan for forbidden
// arithmetic. Avoids a Node `fs`/`url` dependency (this frontend has no
// Node type definitions wired into its app tsconfig) for a single test.
import ownerSummarySource from './ownerSummary.ts?raw';

// =============================================================================
// Fixtures -- every field is a distinct, non-zero value (where the field
// permits) so a mapping bug (e.g. reading the wrong source field) can never
// hide behind two fixtures that coincidentally share a value.
// =============================================================================

const QUICK_INPUTS: AcquisitionRequest = {
  purchase_price: 10_000_000,
  current_noi: 600_000,
  occupancy: 0.95,
  noi_growth: 0.03,
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

const QUICK_RESULTS: AcquisitionResults = {
  going_in_cap_rate: 0.06,
  loan_amount: 6_000_000,
  acquisition_costs: 200_000,
  financing_fee: 60_000,
  initial_equity: 4_260_000,
  monthly_debt_service: 32_209.3,
  annual_debt_service: [386_511.6, 386_511.6, 386_511.6, 386_511.6, 386_511.6],
  remaining_loan_balance: 5_509_723.9,
  noi_by_year: [600_000, 618_000, 636_540, 655_636.2, 675_305.29],
  capex_by_year: [50_000, 50_000, 50_000, 50_000, 50_000],
  exit_noi: 695_564.44,
  exit_value: 10_700_991.46,
  disposition_costs: 267_524.79,
  net_sale_proceeds: 4_923_742.75,
  unlevered_cash_flows: [-9_800_000, 600_000, 618_000, 636_540, 655_636.2, 11_376_296.74],
  levered_cash_flows: [-4_260_000, 213_488.43, 231_488.43, 250_028.43, 269_124.63, 5_480_061.25],
  unlevered_irr: 0.0755,
  levered_irr: 0.1095,
  equity_multiple: 1.611,
  dscr_by_year: [1.5523, 1.5989, 1.6469, 1.6963, 1.7472],
  headline_dscr: 1.5523,
  min_dscr: 1.5523,
  levered_cash_on_cash_by_year: [0.0501, 0.0543, 0.0587, 0.0632, 0.0679],
  unlevered_cash_yield_by_year: [0.0612, 0.0631, 0.065, 0.0669, 0.0689],
  cumulative_operating_distributions_by_year: [
    213_488.43, 444_976.86, 695_005.29, 964_129.93, 1_252_923.64,
  ],
  year_1_debt_yield: 0.1,
};

const DETAILED_TERMS: AcquisitionTermsRequest = {
  purchase_price: 20_000_000,
  hold_period: 7,
  exit_cap_rate: 0.058,
  ltv: 0.55,
  interest_rate: 0.045,
  amortization: 30,
  acquisition_cost_pct: 0.015,
  financing_fee_pct: 0.008,
  disposition_cost_pct: 0.02,
  annual_capex_reserve: 75_000,
  io_period: 1,
};

const DETAILED_OPERATING_INPUTS: DetailedOperatingInputsRequest = {
  gross_potential_rent: 1_800_000,
  other_income: 40_000,
  vacancy_credit_loss_pct: 0.05,
  property_taxes: 150_000,
  insurance: 45_000,
  utilities: 60_000,
  repairs_maintenance: 55_000,
  other_operating_expenses: 30_000,
  management_fee_pct: 0.04,
  revenue_growth: 0.025,
  expense_growth: 0.028,
};

// A Detailed AcquisitionResults over a 7-year hold (deliberately not the
// Quick fixture's 5 -- proves `finalYearNoi` is genuinely the schedule's
// last entry, not a hardcoded "Year 5").
const DETAILED_RESULTS: AcquisitionResults = {
  going_in_cap_rate: 0.055,
  loan_amount: 11_000_000,
  acquisition_costs: 300_000,
  financing_fee: 88_000,
  initial_equity: 9_388_000,
  monthly_debt_service: 55_730.5,
  annual_debt_service: [
    668_766, 668_766, 668_766, 668_766, 668_766, 668_766, 668_766,
  ],
  remaining_loan_balance: 9_812_345.67,
  noi_by_year: [
    1_100_000, 1_127_500, 1_155_688, 1_184_580, 1_214_195, 1_244_550, 1_275_664,
  ],
  capex_by_year: [75_000, 75_000, 75_000, 75_000, 75_000, 75_000, 75_000],
  exit_noi: 1_307_556,
  exit_value: 22_544_069,
  disposition_costs: 450_881.38,
  net_sale_proceeds: 12_281_842.29,
  unlevered_cash_flows: [
    -19_700_000, 1_100_000, 1_127_500, 1_155_688, 1_184_580, 1_214_195, 1_244_550,
    13_557_506.29,
  ],
  levered_cash_flows: [
    -9_388_000, 431_234, 458_734, 486_922, 515_814, 545_429, 575_784, 12_756_752.29,
  ],
  unlevered_irr: 0.0621,
  levered_irr: 0.0838,
  equity_multiple: 1.482,
  dscr_by_year: [1.6449, 1.686, 1.7281, 1.7713, 1.8156, 1.861, 1.9077],
  headline_dscr: 1.6449,
  min_dscr: 1.6449,
  levered_cash_on_cash_by_year: [0.0459, 0.0489, 0.0519, 0.055, 0.0581, 0.0581, 0.0613],
  unlevered_cash_yield_by_year: [0.0558, 0.0573, 0.0587, 0.0601, 0.0616, 0.0632, 0.0648],
  cumulative_operating_distributions_by_year: [
    431_234, 889_968, 1_376_890, 1_892_704, 2_438_133, 2_983_562, 3_559_346,
  ],
  year_1_debt_yield: 0.1,
};

const QUICK_BREAK_EVEN: StandardBreakEvenAnalysis = {
  max_purchase_price: {
    break_even_type: 'max_purchase_price',
    assumption: 'purchase_price',
    metric: 'levered_irr',
    target_metric_value: 0.1,
    baseline_assumption_value: 10_000_000,
    baseline_metric_value: 0.1095,
    solved_assumption_value: 10_450_000,
    solved_metric_value: 0.1,
    lower_search_bound: 1_000_000,
    upper_search_bound: 50_000_000,
    status: 'solved',
  },
  max_exit_cap_rate: {
    break_even_type: 'max_exit_cap_rate',
    assumption: 'exit_cap_rate',
    metric: 'levered_irr',
    target_metric_value: 0.1,
    baseline_assumption_value: 0.065,
    baseline_metric_value: 0.1095,
    solved_assumption_value: 0.071,
    solved_metric_value: 0.1,
    lower_search_bound: 0.01,
    upper_search_bound: 0.2,
    status: 'solved',
  },
  min_noi_growth: {
    break_even_type: 'min_noi_growth',
    assumption: 'noi_growth',
    metric: 'levered_irr',
    target_metric_value: 0.1,
    baseline_assumption_value: 0.03,
    baseline_metric_value: 0.1095,
    solved_assumption_value: 0.021,
    solved_metric_value: 0.1,
    lower_search_bound: -0.1,
    upper_search_bound: 0.5,
    status: 'solved',
  },
  max_interest_rate: {
    break_even_type: 'max_interest_rate',
    assumption: 'interest_rate',
    metric: 'headline_dscr',
    target_metric_value: 1.25,
    baseline_assumption_value: 0.05,
    baseline_metric_value: 1.5523,
    solved_assumption_value: 0.083,
    solved_metric_value: 1.25,
    lower_search_bound: 0.001,
    upper_search_bound: 0.3,
    status: 'solved',
  },
  min_current_noi: {
    break_even_type: 'min_current_noi',
    assumption: 'current_noi',
    metric: 'levered_irr',
    target_metric_value: 0.1,
    baseline_assumption_value: 600_000,
    baseline_metric_value: 0.1095,
    solved_assumption_value: 575_000,
    solved_metric_value: 0.1,
    lower_search_bound: 1,
    upper_search_bound: 100_000_000,
    status: 'solved',
  },
};

const DETAILED_BREAK_EVEN: StandardDetailedBreakEvenAnalysis = {
  max_purchase_price: {
    break_even_type: 'max_purchase_price',
    assumption: 'purchase_price',
    metric: 'levered_irr',
    target_metric_value: 0.09,
    baseline_assumption_value: 20_000_000,
    baseline_metric_value: 0.0838,
    solved_assumption_value: 19_100_000,
    solved_metric_value: 0.09,
    lower_search_bound: 1_000_000,
    upper_search_bound: 100_000_000,
    status: 'solved',
  },
  max_exit_cap_rate: {
    break_even_type: 'max_exit_cap_rate',
    assumption: 'exit_cap_rate',
    metric: 'levered_irr',
    target_metric_value: 0.09,
    baseline_assumption_value: 0.058,
    baseline_metric_value: 0.0838,
    solved_assumption_value: null,
    solved_metric_value: null,
    lower_search_bound: 0.01,
    upper_search_bound: 0.2,
    status: 'no_solution_in_range',
  },
  max_interest_rate: {
    break_even_type: 'max_interest_rate',
    assumption: 'interest_rate',
    metric: 'headline_dscr',
    target_metric_value: 1.25,
    baseline_assumption_value: 0.045,
    baseline_metric_value: 1.6449,
    solved_assumption_value: 0.071,
    solved_metric_value: 1.25,
    lower_search_bound: 0.001,
    upper_search_bound: 0.3,
    status: 'solved',
  },
};

function quickSource(overrides: Partial<OwnerSummarySource & { operatingMode: 'quick' }> = {}) {
  const base: OwnerSummarySource = {
    operatingMode: 'quick',
    dealName: '111 Main St',
    dealContext: 'Value-add, refinance after stabilization.',
    inputs: QUICK_INPUTS,
    results: QUICK_RESULTS,
    breakEven: QUICK_BREAK_EVEN,
  };
  return { ...base, ...overrides } as OwnerSummarySource;
}

function detailedSource(
  overrides: Partial<OwnerSummarySource & { operatingMode: 'detailed' }> = {},
) {
  const base: OwnerSummarySource = {
    operatingMode: 'detailed',
    dealName: '200 Industrial Pkwy',
    dealContext: 'Institutional core-plus hold.',
    terms: DETAILED_TERMS,
    detailedOperatingInputs: DETAILED_OPERATING_INPUTS,
    results: DETAILED_RESULTS,
    breakEven: DETAILED_BREAK_EVEN,
  };
  return { ...base, ...overrides } as OwnerSummarySource;
}

// =============================================================================
// 1-2. Golden-case exact mapping (Detailed, then Quick)
// =============================================================================

describe('buildOwnerSummaryData -- Detailed golden case', () => {
  const summary = buildOwnerSummaryData(detailedSource());

  it('maps identity exactly', () => {
    expect(summary.identity).toEqual({
      dealName: '200 Industrial Pkwy',
      operatingMode: 'detailed',
    });
  });

  it('maps key returns exactly from AcquisitionResults', () => {
    expect(summary.keyReturns).toEqual({
      leveredIrr: 0.0838,
      unleveredIrr: 0.0621,
      equityMultiple: 1.482,
      yearOneLeveredCashOnCash: 0.0459,
      headlineDscr: 1.6449,
      minDscr: 1.6449,
    });
  });

  it('maps owner returns exactly, including the full annual schedules', () => {
    expect(summary.ownerReturns.yearOneLeveredCashOnCash).toBe(0.0459);
    expect(summary.ownerReturns.yearOneDebtYield).toBe(0.1);
    expect(summary.ownerReturns.cumulativeOperatingDistributionsThroughHold).toBe(3_559_346);
    expect(summary.ownerReturns.leveredCashOnCashByYear).toEqual(
      DETAILED_RESULTS.levered_cash_on_cash_by_year,
    );
    expect(summary.ownerReturns.unleveredCashYieldByYear).toEqual(
      DETAILED_RESULTS.unlevered_cash_yield_by_year,
    );
    expect(summary.ownerReturns.cumulativeOperatingDistributionsByYear).toEqual(
      DETAILED_RESULTS.cumulative_operating_distributions_by_year,
    );
  });

  it('maps investment snapshot from AcquisitionTermsRequest + AcquisitionResults', () => {
    expect(summary.investmentSnapshot).toEqual({
      purchasePrice: 20_000_000,
      holdPeriod: 7,
      exitCapRate: 0.058,
      ltv: 0.55,
      interestRate: 0.045,
      ioPeriod: 1,
      loanAmount: 11_000_000,
      yearOneNoi: 1_100_000,
      goingInCapRate: 0.055,
    });
  });

  it('maps debt/risk exactly', () => {
    expect(summary.debtRisk).toEqual({
      loanAmount: 11_000_000,
      ltv: 0.55,
      interestRate: 0.045,
      ioPeriod: 1,
      headlineDscr: 1.6449,
      minDscr: 1.6449,
      yearOneDebtYield: 0.1,
    });
  });

  it('maps the operating story with Detailed growth fields, using the real final year (7, not 5)', () => {
    expect(summary.operatingStory).toEqual({
      operatingMode: 'detailed',
      yearOneNoi: 1_100_000,
      finalYearNoi: 1_275_664,
      revenueGrowth: 0.025,
      expenseGrowth: 0.028,
    });
  });

  it('maps break-even highlights from the three shared StandardDetailedBreakEvenAnalysis fields', () => {
    expect(summary.breakEvenHighlights).toEqual({
      maxPurchasePrice: DETAILED_BREAK_EVEN.max_purchase_price,
      maxExitCapRate: DETAILED_BREAK_EVEN.max_exit_cap_rate,
      maxInterestRate: DETAILED_BREAK_EVEN.max_interest_rate,
    });
  });
});

describe('buildOwnerSummaryData -- Quick golden case', () => {
  const summary = buildOwnerSummaryData(quickSource());

  it('maps identity exactly', () => {
    expect(summary.identity).toEqual({ dealName: '111 Main St', operatingMode: 'quick' });
  });

  it('maps key returns exactly from AcquisitionResults', () => {
    expect(summary.keyReturns).toEqual({
      leveredIrr: 0.1095,
      unleveredIrr: 0.0755,
      equityMultiple: 1.611,
      yearOneLeveredCashOnCash: 0.0501,
      headlineDscr: 1.5523,
      minDscr: 1.5523,
    });
  });

  it('maps investment snapshot from AcquisitionRequest + AcquisitionResults', () => {
    expect(summary.investmentSnapshot).toEqual({
      purchasePrice: 10_000_000,
      holdPeriod: 5,
      exitCapRate: 0.065,
      ltv: 0.6,
      interestRate: 0.05,
      ioPeriod: 2,
      loanAmount: 6_000_000,
      yearOneNoi: 600_000,
      goingInCapRate: 0.06,
    });
  });

  it('maps the operating story with Quick noiGrowth, final year = year 5', () => {
    expect(summary.operatingStory).toEqual({
      operatingMode: 'quick',
      yearOneNoi: 600_000,
      finalYearNoi: 675_305.29,
      noiGrowth: 0.03,
    });
  });

  it('maps break-even highlights from the three shared fields, ignoring min_noi_growth/min_current_noi', () => {
    expect(summary.breakEvenHighlights).toEqual({
      maxPurchasePrice: QUICK_BREAK_EVEN.max_purchase_price,
      maxExitCapRate: QUICK_BREAK_EVEN.max_exit_cap_rate,
      maxInterestRate: QUICK_BREAK_EVEN.max_interest_rate,
    });
  });
});

// =============================================================================
// 3. Fresh result vs. restored snapshot produce identical output
// =============================================================================

describe('restored-snapshot equivalence', () => {
  it('produces byte-identical OwnerSummaryData whether results came from a fresh analyze or a restored snapshot', () => {
    // A restored snapshot is, from this module's point of view, simply
    // another AcquisitionResults object -- there is no "origin" flag
    // anywhere in AcquisitionResults or OwnerSummarySource for the builder
    // to branch on. Deserializing (JSON round-trip, exactly what a
    // persisted snapshot goes through) and rebuilding must match exactly.
    const freshSource = quickSource();
    const restoredSource: OwnerSummarySource = {
      ...freshSource,
      results: JSON.parse(JSON.stringify(QUICK_RESULTS)) as AcquisitionResults,
    };

    expect(buildOwnerSummaryData(restoredSource)).toEqual(buildOwnerSummaryData(freshSource));
  });

  it('also holds for Detailed', () => {
    const freshSource = detailedSource();
    const restoredSource: OwnerSummarySource = {
      ...freshSource,
      results: JSON.parse(JSON.stringify(DETAILED_RESULTS)) as AcquisitionResults,
    };

    expect(buildOwnerSummaryData(restoredSource)).toEqual(buildOwnerSummaryData(freshSource));
  });
});

// =============================================================================
// 4-5. Deal Context passthrough
// =============================================================================

describe('Deal Context passthrough', () => {
  it('passes a non-blank Deal Context through unchanged (trimmed only)', () => {
    const summary = buildOwnerSummaryData(quickSource({ dealContext: '  Value-add play.  ' }));
    expect(summary.dealContext).toBe('Value-add play.');
  });

  it('normalizes null to null', () => {
    const summary = buildOwnerSummaryData(quickSource({ dealContext: null }));
    expect(summary.dealContext).toBeNull();
  });

  it('normalizes an empty string to null', () => {
    const summary = buildOwnerSummaryData(quickSource({ dealContext: '' }));
    expect(summary.dealContext).toBeNull();
  });

  it('normalizes a whitespace-only string to null', () => {
    const summary = buildOwnerSummaryData(quickSource({ dealContext: '   \n\t  ' }));
    expect(summary.dealContext).toBeNull();
  });
});

// =============================================================================
// 6-10. Null/edge-state preservation
// =============================================================================

describe('null and edge-state preservation', () => {
  it('preserves a null Year 1 Debt Yield for an all-cash deal', () => {
    const allCashResults: AcquisitionResults = { ...QUICK_RESULTS, year_1_debt_yield: null };
    const summary = buildOwnerSummaryData(quickSource({ results: allCashResults }));
    expect(summary.ownerReturns.yearOneDebtYield).toBeNull();
    expect(summary.debtRisk.yearOneDebtYield).toBeNull();
  });

  it('preserves a null Year 1 Levered CoC for zero initial equity', () => {
    const zeroEquityResults: AcquisitionResults = {
      ...QUICK_RESULTS,
      levered_cash_on_cash_by_year: [null, null, null, null, null],
    };
    const summary = buildOwnerSummaryData(quickSource({ results: zeroEquityResults }));
    expect(summary.keyReturns.yearOneLeveredCashOnCash).toBeNull();
    expect(summary.ownerReturns.yearOneLeveredCashOnCash).toBeNull();
  });

  it('preserves a negative Year 1 Levered CoC exactly (never clamped to 0 or null)', () => {
    const negativeCoc: AcquisitionResults = {
      ...QUICK_RESULTS,
      levered_cash_on_cash_by_year: [-0.0234, 0.01, 0.02, 0.03, 0.04],
    };
    const summary = buildOwnerSummaryData(quickSource({ results: negativeCoc }));
    expect(summary.keyReturns.yearOneLeveredCashOnCash).toBe(-0.0234);
  });

  it('preserves negative cumulative operating distributions exactly', () => {
    const negativeCumulative: AcquisitionResults = {
      ...QUICK_RESULTS,
      cumulative_operating_distributions_by_year: [
        -50_000, -10_000, 20_000, 90_000, 180_000,
      ],
    };
    const summary = buildOwnerSummaryData(quickSource({ results: negativeCumulative }));
    expect(summary.ownerReturns.cumulativeOperatingDistributionsThroughHold).toBe(180_000);
    expect(summary.ownerReturns.cumulativeOperatingDistributionsByYear[0]).toBe(-50_000);
  });

  it('handles a one-year hold (final year equals year 1, not suppressed)', () => {
    const oneYearResults: AcquisitionResults = {
      ...QUICK_RESULTS,
      noi_by_year: [600_000],
      levered_cash_on_cash_by_year: [0.05],
      unlevered_cash_yield_by_year: [0.06],
      cumulative_operating_distributions_by_year: [213_488.43],
    };
    const oneYearInputs: AcquisitionRequest = { ...QUICK_INPUTS, hold_period: 1 };
    const summary = buildOwnerSummaryData(
      quickSource({ inputs: oneYearInputs, results: oneYearResults }),
    );
    expect(summary.operatingStory.yearOneNoi).toBe(600_000);
    expect(summary.operatingStory.finalYearNoi).toBe(600_000);
    expect(summary.investmentSnapshot.holdPeriod).toBe(1);
  });
});

// =============================================================================
// 11-12. Growth-field mapping
// =============================================================================

describe('growth field mapping', () => {
  it('maps Detailed revenue_growth/expense_growth, never a Quick-style single rate', () => {
    const summary = buildOwnerSummaryData(detailedSource());
    expect(summary.operatingStory).toMatchObject({
      operatingMode: 'detailed',
      revenueGrowth: 0.025,
      expenseGrowth: 0.028,
    });
    expect(summary.operatingStory).not.toHaveProperty('noiGrowth');
  });

  it('maps Quick noi_growth, never a Detailed-style dual rate', () => {
    const summary = buildOwnerSummaryData(quickSource());
    expect(summary.operatingStory).toMatchObject({ operatingMode: 'quick', noiGrowth: 0.03 });
    expect(summary.operatingStory).not.toHaveProperty('revenueGrowth');
    expect(summary.operatingStory).not.toHaveProperty('expenseGrowth');
  });
});

// =============================================================================
// 13-14. Break-even availability
// =============================================================================

describe('break-even availability', () => {
  it('produces no break-even section when break-even has not been computed this session', () => {
    const summary = buildOwnerSummaryData(quickSource({ breakEven: null }));
    expect(summary.breakEvenHighlights).toBeNull();
  });

  it('produces no break-even section for Detailed either', () => {
    const summary = buildOwnerSummaryData(detailedSource({ breakEven: null }));
    expect(summary.breakEvenHighlights).toBeNull();
  });

  it('maps available break-even to the exact existing BreakEvenResult objects, unmodified', () => {
    const summary = buildOwnerSummaryData(quickSource());
    expect(summary.breakEvenHighlights?.maxPurchasePrice).toBe(QUICK_BREAK_EVEN.max_purchase_price);
    expect(summary.breakEvenHighlights?.maxExitCapRate).toBe(QUICK_BREAK_EVEN.max_exit_cap_rate);
    expect(summary.breakEvenHighlights?.maxInterestRate).toBe(QUICK_BREAK_EVEN.max_interest_rate);
  });

  it('preserves a no_solution_in_range break-even result exactly, never fabricating a solved value', () => {
    const summary = buildOwnerSummaryData(detailedSource());
    expect(summary.breakEvenHighlights?.maxExitCapRate.status).toBe('no_solution_in_range');
    expect(summary.breakEvenHighlights?.maxExitCapRate.solved_assumption_value).toBeNull();
  });
});

// =============================================================================
// 15. No sensitivity/break-even recomputation
// =============================================================================

describe('no recomputation of break-even', () => {
  it('never mutates or recomputes the supplied break-even objects', () => {
    const source = quickSource();
    const originalMaxPurchasePrice = source.breakEven?.max_purchase_price;
    buildOwnerSummaryData(source);
    expect(source.breakEven?.max_purchase_price).toBe(originalMaxPurchasePrice);
    expect(source.breakEven?.max_purchase_price.solved_assumption_value).toBe(10_450_000);
  });
});

// =============================================================================
// 17. No cross-mode leakage
// =============================================================================

describe('no Quick/Detailed cross-mode leakage', () => {
  it('a Quick OwnerSummaryData never carries Detailed-only operating-story fields', () => {
    const summary = buildOwnerSummaryData(quickSource());
    expect(Object.keys(summary.operatingStory).sort()).toEqual(
      ['finalYearNoi', 'noiGrowth', 'operatingMode', 'yearOneNoi'].sort(),
    );
  });

  it('a Detailed OwnerSummaryData never carries Quick-only operating-story fields', () => {
    const summary = buildOwnerSummaryData(detailedSource());
    expect(Object.keys(summary.operatingStory).sort()).toEqual(
      ['expenseGrowth', 'finalYearNoi', 'operatingMode', 'revenueGrowth', 'yearOneNoi'].sort(),
    );
  });
});

// =============================================================================
// 18. Deal-Context-only difference changes context but not numerical fields
// =============================================================================

describe('Deal-Context-only difference', () => {
  it('changes dealContext without altering any numerical group', () => {
    const before = buildOwnerSummaryData(quickSource({ dealContext: 'Original strategy.' }));
    const after = buildOwnerSummaryData(quickSource({ dealContext: 'Updated strategy.' }));

    expect(before.dealContext).toBe('Original strategy.');
    expect(after.dealContext).toBe('Updated strategy.');
    expect(after.keyReturns).toEqual(before.keyReturns);
    expect(after.ownerReturns).toEqual(before.ownerReturns);
    expect(after.investmentSnapshot).toEqual(before.investmentSnapshot);
    expect(after.debtRisk).toEqual(before.debtRisk);
    expect(after.operatingStory).toEqual(before.operatingStory);
    expect(after.breakEvenHighlights).toEqual(before.breakEvenHighlights);
  });
});

// =============================================================================
// 16/25. Architecture guardrail -- no financial arithmetic in the builder.
//
// Strips comments, the single import statement, and string literals, then
// asserts no multiplication/division operator survives anywhere, and that
// every remaining "-" is part of the one explicitly-permitted idiom
// (`.length - 1`, trivial last-index selection) -- never a subtraction
// between two authoritative values. Not a blanket "no operators" ban (that
// would also forbid the permitted array-index arithmetic); a targeted
// check for the specific forbidden shape: value OP value.
// =============================================================================

describe('ownerSummary.ts architecture guardrail: no financial formulas', () => {
  const rawSource = ownerSummarySource;

  function stripNonExecutableText(source: string): string {
    return source
      .replace(/\/\*[\s\S]*?\*\//g, '') // block comments, including JSDoc
      .replace(/\/\/.*$/gm, '') // line comments
      .replace(/import[\s\S]*?from\s*'[^']*';/g, '') // the module's one import statement
      .replace(/'[^']*'/g, "''"); // string literals (drop contents, keep quotes)
  }

  it('contains no multiplication or division operator anywhere in executable code', () => {
    const executable = stripNonExecutableText(rawSource);
    expect(executable).not.toMatch(/[*/]/);
  });

  it('contains no addition operator anywhere in executable code', () => {
    const executable = stripNonExecutableText(rawSource);
    expect(executable).not.toMatch(/\+/);
  });

  it('uses "-" only for the explicitly-permitted `.length - 1` last-index idiom', () => {
    const executable = stripNonExecutableText(rawSource);
    const linesWithMinus = executable.split('\n').filter((line) => line.includes('-'));
    for (const line of linesWithMinus) {
      expect(line).toMatch(/\.length\s*-\s*1\b/);
    }
  });

  it('never calls Array#reduce, Math.*, or any averaging/summing helper', () => {
    expect(rawSource).not.toMatch(/\.reduce\(/);
    expect(rawSource).not.toMatch(/Math\./);
  });
});
