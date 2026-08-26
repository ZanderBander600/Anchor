import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import {
  analyzeAcquisition,
  ApiError,
  fetchAIAnalysis,
  fetchBreakEvenAnalysis,
  fetchSensitivityPresets,
} from './api';
import type {
  AcquisitionResults,
  AIAnalysis,
  BreakEvenResult,
  StandardBreakEvenAnalysis,
  StandardSensitivityPresets,
  TwoWaySensitivityResult,
} from './types';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    analyzeAcquisition: vi.fn(),
    fetchSensitivityPresets: vi.fn(),
    fetchBreakEvenAnalysis: vi.fn(),
    fetchAIAnalysis: vi.fn(),
  };
});

const mockAnalyze = vi.mocked(analyzeAcquisition);
const mockFetchSensitivityPresets = vi.mocked(fetchSensitivityPresets);
const mockFetchBreakEvenAnalysis = vi.mocked(fetchBreakEvenAnalysis);
const mockFetchAIAnalysis = vi.mocked(fetchAIAnalysis);

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

function makeResults(overrides: Partial<AcquisitionResults> = {}): AcquisitionResults {
  return {
    going_in_cap_rate: 0.05,
    loan_amount: 32_500_000,
    initial_equity: 17_500_000,
    monthly_debt_service: 179_466.2,
    annual_debt_service: [
      2153594.44, 2153594.44, 2153594.44, 2153594.44, 2153594.44,
    ],
    remaining_loan_balance: 30_000_000,
    noi_by_year: [2500000, 2575000, 2652250, 2731817.5, 2813772.03],
    exit_noi: 2898185.19,
    exit_value: 52694276.18,
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
  mockFetchSensitivityPresets.mockReset();
  mockFetchSensitivityPresets.mockResolvedValue(makeSensitivityPresets());
  mockFetchBreakEvenAnalysis.mockReset();
  mockFetchBreakEvenAnalysis.mockResolvedValue(makeBreakEvenAnalysis());
  mockFetchAIAnalysis.mockReset();
  mockFetchAIAnalysis.mockResolvedValue(makeAiAnalysis());
});

afterEach(() => {
  cleanup();
});

describe('App workflow', () => {
  it('renders the golden defaults in the form', () => {
    render(<App />);

    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '50000000');
    expect(screen.getByLabelText(/^Current NOI/)).toHaveProperty('value', '2500000');
    expect(screen.getByLabelText(/^Occupancy/)).toHaveProperty('value', '95');
    expect(screen.getByLabelText(/^Hold Period/)).toHaveProperty('value', '5');
    expect(screen.getByLabelText(/^Exit Cap Rate/)).toHaveProperty('value', '5.5');
    expect(screen.getByLabelText(/^LTV/)).toHaveProperty('value', '65');
  });

  it('shows key results after a successful analysis', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    expect(await screen.findByText('7.91%')).toBeTruthy();
    expect(screen.getByText('1.44x')).toBeTruthy();
  });

  it('clears displayed results when an assumption is edited after a successful analysis', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);

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
      }),
    );
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    const naValues = await screen.findAllByText('N/A');
    expect(naValues.length).toBeGreaterThanOrEqual(4);
  });

  it('converts percentage inputs to decimals exactly once when submitting', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);

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
    });
  });
});

describe('Sensitivity analysis workflow', () => {
  it('runs and displays the sensitivity section only after a successful base analysis', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);

    expect(screen.queryByText('Sensitivity Analysis')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    expect(await screen.findByText('Sensitivity Analysis')).toBeTruthy();
    expect(mockFetchSensitivityPresets).toHaveBeenCalledTimes(1);
  });

  it('passes the same raw-decimal request to sensitivity as to the base analysis', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    await screen.findByText('Sensitivity Analysis');

    expect(mockFetchSensitivityPresets).toHaveBeenCalledWith(mockAnalyze.mock.calls[0][0]);
  });

  it('clears sensitivity results when an assumption is edited after a successful analysis', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);

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

    expect(screen.queryByText('Break-Even Analysis')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    expect(await screen.findByText('Break-Even Analysis')).toBeTruthy();
    expect(mockFetchBreakEvenAnalysis).toHaveBeenCalledTimes(1);
  });

  it('renders default hurdle controls and all five result cards', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);

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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    expect(await screen.findByText('Not found in tested range')).toBeTruthy();
    expect(screen.queryByText(/impossible/i)).toBeNull();
    expect(screen.queryByText(/no solution exists/i)).toBeNull();
  });

  it('clears break-even results when a base assumption is edited', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);

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

    expect(screen.queryByText('Anchor AI Analyst')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));

    expect(await screen.findByText('Anchor AI Analyst')).toBeTruthy();
    expect(mockFetchAIAnalysis).not.toHaveBeenCalled();
  });

  it('does not auto-generate an AI analysis after the base analysis completes', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    await screen.findByText('Anchor AI Analyst');
    await screen.findByText('Break-Even Analysis');

    expect(mockFetchAIAnalysis).not.toHaveBeenCalled();
  });

  it('generates an AI analysis only when the Generate button is clicked', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    render(<App />);

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
    );
  });

  it('shows a loading state and disables the Generate button while pending', async () => {
    const user = userEvent.setup();
    mockAnalyze.mockResolvedValue(makeResults());
    const pending = deferred<AIAnalysis>();
    mockFetchAIAnalysis.mockReturnValueOnce(pending.promise);
    render(<App />);

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

    await user.click(screen.getByRole('button', { name: 'Analyze Deal' }));
    await screen.findByText('Anchor AI Analyst');
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    await screen.findByText('Investment View');

    expect(document.body.innerHTML).not.toMatch(/sk-[A-Za-z0-9]/);
    expect(document.body.innerHTML.toLowerCase()).not.toContain('openai_api_key');
  });
});
