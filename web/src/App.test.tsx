import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import { analyzeAcquisition, ApiError } from './api';
import type { AcquisitionResults } from './types';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    analyzeAcquisition: vi.fn(),
  };
});

const mockAnalyze = vi.mocked(analyzeAcquisition);

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

beforeEach(() => {
  mockAnalyze.mockReset();
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
