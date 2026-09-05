import { describe, expect, it } from 'vitest';
import { BASE_LIVE_METRIC_IDS, liveMetricsFor } from './liveMetrics';
import type { AcquisitionResults } from './types';

function makeResults(overrides: Partial<AcquisitionResults> = {}): AcquisitionResults {
  return {
    going_in_cap_rate: 0.06,
    loan_amount: 32_500_000,
    acquisition_costs: 1_000_000,
    financing_fee: 325_000,
    initial_equity: 18_825_000,
    monthly_debt_service: 186_000,
    annual_debt_service: [2_232_000, 2_232_000],
    remaining_loan_balance: 30_100_000,
    noi_by_year: [3_000_000, 3_090_000, 3_182_700],
    capex_by_year: [50_000, 50_000, 50_000],
    exit_noi: 3_278_181,
    exit_value: 59_603_290,
    disposition_costs: 1_490_082,
    net_sale_proceeds: 28_013_208,
    unlevered_cash_flows: [-51_000_000, 2_950_000],
    levered_cash_flows: [-18_825_000, 718_000],
    unlevered_irr: 0.0614,
    levered_irr: 0.0791,
    equity_multiple: 1.38,
    dscr_by_year: [1.34, 1.38],
    headline_dscr: 1.34,
    min_dscr: 1.34,
    levered_cash_on_cash_by_year: [0.0381, 0.0429],
    unlevered_cash_yield_by_year: [0.0578, 0.0596],
    cumulative_operating_distributions_by_year: [718_000, 1_526_000],
    year_1_debt_yield: 0.0923,
    ...overrides,
  };
}

describe('Live Case metrics', () => {
  it('emphasises four metrics per Underwrite tab', () => {
    const results = makeResults();
    for (const tab of ['acquisition', 'operations', 'debt', 'exit', 'results'] as const) {
      expect(liveMetricsFor(tab, results)).toHaveLength(4);
    }
  });

  it('shows the headline returns as the base case', () => {
    expect(BASE_LIVE_METRIC_IDS).toEqual([
      'levered_irr',
      'equity_multiple',
      'year_1_coc',
      'year_1_dscr',
    ]);
  });

  it('reads authoritative engine values verbatim, only formatted', () => {
    const metrics = liveMetricsFor('results', makeResults());
    expect(metrics.map((m) => [m.label, m.value])).toEqual([
      ['Levered IRR', '7.91%'],
      ['Equity Multiple', '1.38x'],
      ['Year 1 Levered CoC', '3.81%'],
      ['Year 1 DSCR', '1.34x'],
    ]);
    expect(metrics[3].caption).toBe('Min 1.34x');
  });

  it('surfaces the metrics each tab’s own assumptions move', () => {
    const results = makeResults();
    expect(liveMetricsFor('debt', results).map((m) => m.label)).toEqual([
      'Loan Amount',
      'Year 1 DSCR',
      'Minimum DSCR',
      'Year 1 Debt Yield',
    ]);
    expect(liveMetricsFor('exit', results).map((m) => m.label)).toEqual([
      'Exit NOI',
      'Exit Value',
      'Net Sale Proceeds',
      'Levered IRR',
    ]);
    expect(liveMetricsFor('operations', results).map((m) => m.value)).toEqual([
      '$3,000,000',
      '$3,182,700',
      '7.91%',
      '3.81%',
    ]);
    expect(liveMetricsFor('acquisition', results).map((m) => m.value)).toEqual([
      '7.91%',
      '1.38x',
      '$18,825,000',
      '6.00%',
    ]);
  });

  it('shows N/A for a metric the engine returned as null, never a zero', () => {
    const metrics = liveMetricsFor(
      'results',
      makeResults({
        levered_irr: null,
        equity_multiple: null,
        levered_cash_on_cash_by_year: [null],
        dscr_by_year: [null],
        min_dscr: null,
      }),
    );
    expect(metrics.map((m) => m.value)).toEqual(['N/A', 'N/A', 'N/A', 'N/A']);
    // With no Minimum DSCR there is no caption to fabricate either.
    expect(metrics[3].caption).toBeUndefined();
  });

  it('shows N/A rather than $0 when a series the engine produced is empty', () => {
    const metrics = liveMetricsFor('operations', makeResults({ noi_by_year: [] }));
    expect(metrics[0].value).toBe('N/A');
    expect(metrics[1].value).toBe('N/A');
  });

  it('preserves the sign of a negative engine value', () => {
    const metrics = liveMetricsFor(
      'results',
      makeResults({ levered_irr: -0.0425, equity_multiple: 0.62 }),
    );
    expect(metrics[0].value).toBe('-4.25%');
    expect(metrics[1].value).toBe('0.62x');

    const exit = liveMetricsFor('exit', makeResults({ net_sale_proceeds: -1_250_000 }));
    expect(exit[2].value).toBe('-$1,250,000');
  });
});
