import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import { OwnerSummaryPanel } from './OwnerSummaryPanel';
import { buildOwnerSummaryData } from '../ownerSummary';
import type { OwnerSummarySource } from '../ownerSummary';
import type {
  AcquisitionRequest,
  AcquisitionResults,
  AcquisitionTermsRequest,
  DetailedOperatingInputsRequest,
  StandardBreakEvenAnalysis,
} from '../types';

afterEach(() => {
  cleanup();
});

// =============================================================================
// The frozen Underwriting V2 golden case (App.test.tsx's `makeV2GoldenResults`,
// reused unmodified by its own `makeDetailedResults` for the Detailed test
// path too) -- the same authoritative numbers Gate B3's spec cites for
// "golden display" verification. Never reproduced via a TypeScript formula.
// =============================================================================

const GOLDEN_RESULTS: AcquisitionResults = {
  going_in_cap_rate: 0.06,
  loan_amount: 6_000_000,
  acquisition_costs: 200_000,
  financing_fee: 60_000,
  initial_equity: 4_260_000,
  monthly_debt_service: 32209.29738072834,
  annual_debt_service: [300_000, 300_000, 386511.5685687402, 386511.5685687402, 386511.5685687402],
  remaining_loan_balance: 5720615.679740943,
  noi_by_year: [600_000, 618_000, 636_540, 655_636.2, 675_305.286],
  capex_by_year: [50_000, 50_000, 50_000, 50_000, 50_000],
  exit_noi: 675_305.286,
  exit_value: 10_700_991.455076924,
  disposition_costs: 267_524.7863769231,
  net_sale_proceeds: 4_712_850.988959057,
  unlevered_cash_flows: [-10_200_000, 550_000, 568_000, 586_540, 605_636.2, 11_058_771.9547],
  levered_cash_flows: [-4_260_000, 250_000, 268_000, 200_028.43143125979, 219_124.63143125974, 4_951_644.7063903175],
  unlevered_irr: 0.061388193938218594,
  levered_irr: 0.07380240064972221,
  equity_multiple: 1.3823468941908068,
  dscr_by_year: [2.0, 2.06, 1.6468847293681788, 1.696291271249224, 1.7471800093867011],
  headline_dscr: 2.0,
  min_dscr: 1.6468847293681788,
  levered_cash_on_cash_by_year: [
    0.05868544600938967, 0.06291079812206572, 0.0469550308524084, 0.05143770690874642,
    0.05605486324677459,
  ],
  unlevered_cash_yield_by_year: [
    0.05392156862745098, 0.05568627450980392, 0.05750392156862745, 0.05937609803921568,
    0.061304439803921564,
  ],
  cumulative_operating_distributions_by_year: [
    250_000, 518_000, 718_028.4314312598, 937_153.0628625196, 1_175_946.7802937794,
  ],
  year_1_debt_yield: 0.1,
};

const GOLDEN_INPUTS: AcquisitionRequest = {
  purchase_price: 10_000_000,
  current_noi: 600_000,
  occupancy: 0.95,
  noi_growth: 0.03,
  hold_period: 5,
  exit_cap_rate: 0.055,
  ltv: 0.6,
  interest_rate: 0.05,
  amortization: 30,
  acquisition_cost_pct: 0.02,
  financing_fee_pct: 0.01,
  disposition_cost_pct: 0.025,
  annual_capex_reserve: 50_000,
  io_period: 2,
};

const GOLDEN_TERMS: AcquisitionTermsRequest = {
  purchase_price: 10_000_000,
  hold_period: 5,
  exit_cap_rate: 0.055,
  ltv: 0.6,
  interest_rate: 0.05,
  amortization: 30,
  acquisition_cost_pct: 0.02,
  financing_fee_pct: 0.01,
  disposition_cost_pct: 0.025,
  annual_capex_reserve: 50_000,
  io_period: 2,
};

const GOLDEN_DETAILED_OPERATING_INPUTS: DetailedOperatingInputsRequest = {
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

function quickSource(overrides: Partial<OwnerSummarySource> = {}): OwnerSummarySource {
  return {
    operatingMode: 'quick',
    dealName: '111 Main St',
    dealContext: null,
    inputs: GOLDEN_INPUTS,
    results: GOLDEN_RESULTS,
    breakEven: null,
    ...overrides,
  } as OwnerSummarySource;
}

function detailedSource(overrides: Partial<OwnerSummarySource> = {}): OwnerSummarySource {
  return {
    operatingMode: 'detailed',
    dealName: '200 Industrial Pkwy',
    dealContext: null,
    terms: GOLDEN_TERMS,
    detailedOperatingInputs: GOLDEN_DETAILED_OPERATING_INPUTS,
    results: GOLDEN_RESULTS,
    breakEven: null,
    ...overrides,
  } as OwnerSummarySource;
}

const GOLDEN_BREAK_EVEN: StandardBreakEvenAnalysis = {
  max_purchase_price: {
    break_even_type: 'max_purchase_price',
    assumption: 'purchase_price',
    metric: 'levered_irr',
    target_metric_value: 0.1,
    baseline_assumption_value: 10_000_000,
    baseline_metric_value: 0.0738,
    solved_assumption_value: 9_400_000,
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
    baseline_assumption_value: 0.055,
    baseline_metric_value: 0.0738,
    solved_assumption_value: null,
    solved_metric_value: null,
    lower_search_bound: 0.01,
    upper_search_bound: 0.2,
    status: 'no_solution_in_range',
  },
  min_noi_growth: {
    break_even_type: 'min_noi_growth',
    assumption: 'noi_growth',
    metric: 'levered_irr',
    target_metric_value: 0.1,
    baseline_assumption_value: 0.03,
    baseline_metric_value: 0.0738,
    solved_assumption_value: 0.09,
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
    baseline_metric_value: 2.0,
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
    baseline_metric_value: 0.0738,
    solved_assumption_value: 650_000,
    solved_metric_value: 0.1,
    lower_search_bound: 1,
    upper_search_bound: 100_000_000,
    status: 'solved',
  },
};

// =============================================================================
// 1-2 (component-level): renders for both modes.
// =============================================================================

describe('OwnerSummaryPanel rendering', () => {
  it('renders for a Quick summary', () => {
    render(<OwnerSummaryPanel data={buildOwnerSummaryData(quickSource())} />);
    expect(screen.getByText('111 Main St')).toBeTruthy();
    expect(screen.getByText('Quick Underwrite')).toBeTruthy();
  });

  it('renders for a Detailed summary', () => {
    render(<OwnerSummaryPanel data={buildOwnerSummaryData(detailedSource())} />);
    expect(screen.getByText('200 Industrial Pkwy')).toBeTruthy();
    expect(screen.getByText('Detailed Underwrite')).toBeTruthy();
  });

  // 23. Quick/Detailed use the same component -- proven structurally: both
  // renders above go through the exact same `OwnerSummaryPanel` import,
  // never a `QuickOwnerSummaryPanel`/`DetailedOwnerSummaryPanel` split.
});

// =============================================================================
// 4-6, 27. Hero metrics + supporting metrics + golden display values.
// =============================================================================

describe('golden display values (Underwriting V2 golden case)', () => {
  beforeEach(() => {
    render(<OwnerSummaryPanel data={buildOwnerSummaryData(quickSource())} />);
  });

  it('renders the four hero metrics with the DSCR headline+minimum caption pattern', () => {
    expect(screen.getByText('7.38%')).toBeTruthy(); // Levered IRR
    expect(screen.getByText('1.38x')).toBeTruthy(); // Equity Multiple
    // Year 1 Levered CoC appears twice by design (hero card + Owner Returns row).
    expect(screen.getAllByText('5.87%').length).toBe(2);
    expect(screen.getAllByText('2.00x').length).toBeGreaterThan(0); // Year 1 DSCR
    expect(screen.getByText('Minimum DSCR: 1.65x')).toBeTruthy();
  });

  it('renders the supporting metrics', () => {
    expect(screen.getByText('6.14%')).toBeTruthy(); // Unlevered IRR
    expect(screen.getAllByText('10.00%').length).toBeGreaterThan(0); // Year 1 Debt Yield
    expect(screen.getAllByText('$1,175,947').length).toBeGreaterThan(0); // Cumulative Distributions
    expect(screen.getAllByText('$600,000').length).toBeGreaterThan(0); // Year 1 NOI
  });

  it('gives the four hero cards more visual weight than the supporting rows (distinct DOM roles)', () => {
    // Hero cards use `.stat-value-primary`; supporting figures use the
    // plain `.info-value` row style -- never identical markup, per the
    // "not all eight metrics get equal visual weight" requirement.
    const heroValues = document.querySelectorAll('.stat-value-primary');
    const infoValues = document.querySelectorAll('.info-value');
    expect(heroValues.length).toBe(4);
    expect(infoValues.length).toBeGreaterThan(0);
  });
});

// =============================================================================
// 7-8. Deal Context / THE PLAY.
// =============================================================================

describe('Deal Context (THE PLAY)', () => {
  it('renders Deal Context under THE PLAY when present', () => {
    const data = buildOwnerSummaryData(
      quickSource({ dealContext: 'Value-add, refinance after stabilization.' }),
    );
    render(<OwnerSummaryPanel data={data} />);
    expect(screen.getByText('The Play')).toBeTruthy();
    expect(screen.getByText('Value-add, refinance after stabilization.')).toBeTruthy();
  });

  it('omits THE PLAY entirely when Deal Context is blank', () => {
    const data = buildOwnerSummaryData(quickSource({ dealContext: null }));
    render(<OwnerSummaryPanel data={data} />);
    expect(screen.queryByText('The Play')).toBeNull();
  });

  it('never labels Deal Context as AI, Verified, or an underwriting assumption', () => {
    const data = buildOwnerSummaryData(quickSource({ dealContext: 'Stated strategy.' }));
    render(<OwnerSummaryPanel data={data} />);
    expect(screen.queryByText(/\bAI\b/)).toBeNull();
    expect(screen.queryByText(/Verified/i)).toBeNull();
    expect(screen.queryByText(/Underwriting assumption/i)).toBeNull();
  });
});

// =============================================================================
// 9-10. Operating story (Quick vs Detailed growth fields).
// =============================================================================

describe('Operating Story', () => {
  it('shows NOI Growth for Quick', () => {
    render(<OwnerSummaryPanel data={buildOwnerSummaryData(quickSource())} />);
    expect(screen.getByText('NOI Growth')).toBeTruthy();
    expect(screen.getByText('3.00%')).toBeTruthy();
    expect(screen.queryByText('Revenue Growth')).toBeNull();
    expect(screen.queryByText('Expense Growth')).toBeNull();
  });

  it('shows Revenue Growth and Expense Growth for Detailed, never NOI Growth', () => {
    render(<OwnerSummaryPanel data={buildOwnerSummaryData(detailedSource())} />);
    expect(screen.getByText('Revenue Growth')).toBeTruthy();
    expect(screen.getByText('Expense Growth')).toBeTruthy();
    expect(screen.queryByText('NOI Growth')).toBeNull();
  });

  it('labels the final hold-year NOI using the deal\'s real hold period', () => {
    render(<OwnerSummaryPanel data={buildOwnerSummaryData(quickSource())} />);
    expect(screen.getByText('Year 5 NOI')).toBeTruthy();
  });
});

// =============================================================================
// 11-12. Break-even highlights.
// =============================================================================

describe('Break-Even Highlights', () => {
  it('renders the break-even section when available', () => {
    const data = buildOwnerSummaryData(quickSource({ breakEven: GOLDEN_BREAK_EVEN }));
    render(<OwnerSummaryPanel data={data} />);
    expect(screen.getByText('Break-Even Highlights')).toBeTruthy();
    expect(screen.getByText('$9,400,000')).toBeTruthy();
    expect(screen.getByText('No solution within tested range')).toBeTruthy();
    expect(screen.getByText('8.30%')).toBeTruthy();
  });

  it('omits the break-even section entirely when null -- no N/A, no placeholder, no warning', () => {
    const data = buildOwnerSummaryData(quickSource({ breakEven: null }));
    render(<OwnerSummaryPanel data={data} />);
    expect(screen.queryByText('Break-Even Highlights')).toBeNull();
    expect(screen.queryByText(/run break-even/i)).toBeNull();
  });
});

// =============================================================================
// 13-17. Null/edge-case display.
// =============================================================================

describe('null and edge-case display', () => {
  it('shows N/A for an all-cash deal\'s Year 1 Debt Yield', () => {
    const allCash: AcquisitionResults = { ...GOLDEN_RESULTS, year_1_debt_yield: null };
    render(<OwnerSummaryPanel data={buildOwnerSummaryData(quickSource({ results: allCash }))} />);
    expect(screen.getAllByText('N/A').length).toBeGreaterThan(0);
  });

  it('shows N/A for zero-initial-equity Year 1 Levered CoC', () => {
    const zeroEquity: AcquisitionResults = {
      ...GOLDEN_RESULTS,
      levered_cash_on_cash_by_year: [null, null, null, null, null],
    };
    render(<OwnerSummaryPanel data={buildOwnerSummaryData(quickSource({ results: zeroEquity }))} />);
    expect(screen.getAllByText('N/A').length).toBeGreaterThan(0);
  });

  it('displays a negative Year 1 Levered CoC as a negative percentage', () => {
    const negativeCoc: AcquisitionResults = {
      ...GOLDEN_RESULTS,
      levered_cash_on_cash_by_year: [-0.0234, 0.01, 0.02, 0.03, 0.04],
    };
    render(<OwnerSummaryPanel data={buildOwnerSummaryData(quickSource({ results: negativeCoc }))} />);
    // Appears twice by design (hero card + Owner Returns row).
    expect(screen.getAllByText('-2.34%').length).toBe(2);
  });

  it('displays negative cumulative distributions as negative currency', () => {
    const negativeCumulative: AcquisitionResults = {
      ...GOLDEN_RESULTS,
      cumulative_operating_distributions_by_year: [-50_000, -10_000, 20_000, 90_000, -180_000],
    };
    render(
      <OwnerSummaryPanel data={buildOwnerSummaryData(quickSource({ results: negativeCumulative }))} />,
    );
    expect(screen.getAllByText('-$180,000').length).toBeGreaterThan(0);
  });

  it('renders a one-year hold coherently, without a duplicate Year 1 NOI row', () => {
    const oneYearResults: AcquisitionResults = {
      ...GOLDEN_RESULTS,
      noi_by_year: [600_000],
      levered_cash_on_cash_by_year: [0.05],
      unlevered_cash_yield_by_year: [0.06],
      cumulative_operating_distributions_by_year: [213_488.43],
    };
    const oneYearInputs: AcquisitionRequest = { ...GOLDEN_INPUTS, hold_period: 1 };
    render(
      <OwnerSummaryPanel
        data={buildOwnerSummaryData(
          quickSource({ inputs: oneYearInputs, results: oneYearResults }),
        )}
      />,
    );
    // "Year 1 NOI" legitimately appears twice overall (the Key Returns
    // supporting row + Operating Story), but Operating Story itself must
    // never show it twice under two different-looking labels (Year 1 NOI
    // *and* a redundant "Year 1 NOI" final-hold-year row).
    const operatingStorySection = screen.getByText('Operating Story').closest('section');
    expect(operatingStorySection).not.toBeNull();
    const noiRowsInOperatingStory = within(operatingStorySection as HTMLElement).getAllByText(
      'Year 1 NOI',
    );
    expect(noiRowsInOperatingStory.length).toBe(1);
  });

  it('never renders NaN, Infinity, undefined, or a bare "null"', () => {
    render(<OwnerSummaryPanel data={buildOwnerSummaryData(quickSource())} />);
    const bodyText = document.body.textContent ?? '';
    expect(bodyText).not.toMatch(/NaN/);
    expect(bodyText).not.toMatch(/Infinity/);
    expect(bodyText).not.toMatch(/undefined/);
    expect(bodyText).not.toMatch(/\bnull\b/);
  });
});

// =============================================================================
// 22, 25. No financial calculation in the component; only formatter calls.
// =============================================================================

describe('architecture guardrail: no financial formulas in the component', () => {
  it('contains no multiplication, division, or addition operator, and only the two explicitly-permitted subtractions', async () => {
    const source = await import('./OwnerSummaryPanel.tsx?raw');
    const raw: string = source.default;
    const executable = raw
      .replace(/\/\*[\s\S]*?\*\//g, '') // block comments, including JSDoc
      .replace(/\/\/.*$/gm, '') // line comments
      .replace(/'[^']*'/g, "''")
      .replace(/"[^"]*"/g, '""')
      // JSX-only "/" occurrences -- self-closing tags (`<InfoRow ... />`)
      // and closing tags (`</div>`, `</>`) -- neither is a division
      // operator. Everything else in this file is plain TSX/JS.
      .replace(/\/>/g, '>')
      .replace(/<\//g, '<')
      // The one JSX *text content* "/" that isn't a quoted string literal
      // (so the quote-stripping above doesn't touch it): the "Debt / Risk"
      // section heading uses "/" as plain punctuation, not code.
      .replace(/Debt \/ Risk/g, 'Debt Risk');
    // Template literals (e.g. `${ioPeriod} years`) are deliberately left
    // intact -- stripping them would blind this check to arithmetic hidden
    // inside a `${...}` interpolation, exactly the case this guardrail
    // exists to catch.

    expect(executable).not.toMatch(/[*/]/);
    expect(executable).not.toMatch(/\+/);
  });
});
