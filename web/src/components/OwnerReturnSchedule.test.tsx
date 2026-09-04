import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { OwnerReturnSchedule } from './OwnerReturnSchedule';
import type { AcquisitionResults } from '../types';

afterEach(() => {
  cleanup();
});

/** A 5-year hold with distinguishable values at every index, mirroring
 * CashFlowTable.test.tsx's RESULTS convention -- fields the component
 * doesn't read get trivial placeholder values. */
const RESULTS: AcquisitionResults = {
  going_in_cap_rate: 0.06,
  loan_amount: 6_000_000,
  acquisition_costs: 200_000,
  financing_fee: 60_000,
  initial_equity: 4_260_000,
  monthly_debt_service: 1,
  annual_debt_service: [300_000, 300_000, 386_511.57, 386_511.57, 386_511.57],
  remaining_loan_balance: 1,
  noi_by_year: [600_000, 618_000, 636_540, 655_636.2, 675_305.29],
  capex_by_year: [50_000, 50_000, 50_000, 50_000, 50_000],
  exit_noi: 1,
  exit_value: 1,
  disposition_costs: 1,
  // Deliberately huge sale-inclusive terminal cash flows -- proves the
  // schedule never reads these for its own final-year row.
  unlevered_cash_flows: [-10_200_000, 550_000, 568_000, 586_540, 605_636.2, 11_058_771.95],
  levered_cash_flows: [-4_260_000, 250_000, 268_000, 200_028.43, 219_124.63, 4_951_644.71],
  net_sale_proceeds: 4_712_850.99,
  unlevered_irr: 1,
  levered_irr: 1,
  equity_multiple: 1,
  dscr_by_year: [1, 1, 1, 1, 1],
  headline_dscr: 1,
  min_dscr: 1,
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

function rowTexts(row: HTMLTableRowElement): string[] {
  return Array.from(row.querySelectorAll('td')).map((cell) => cell.textContent ?? '');
}

describe('OwnerReturnSchedule', () => {
  it('renders the annual Levered CoC schedule', () => {
    render(<OwnerReturnSchedule results={RESULTS} />);

    const rows = screen.getAllByRole('row').slice(1); // skip header
    expect(rowTexts(rows[0] as HTMLTableRowElement)).toEqual([
      '1',
      '5.87%',
      '5.39%',
      '$250,000',
    ]);
    expect(rowTexts(rows[1] as HTMLTableRowElement)[1]).toBe('6.29%');
    expect(rowTexts(rows[2] as HTMLTableRowElement)[1]).toBe('4.70%');
    expect(rowTexts(rows[3] as HTMLTableRowElement)[1]).toBe('5.14%');
    expect(rowTexts(rows[4] as HTMLTableRowElement)[1]).toBe('5.61%');
  });

  it('renders the annual Unlevered Cash Yield schedule', () => {
    render(<OwnerReturnSchedule results={RESULTS} />);

    const rows = screen.getAllByRole('row').slice(1);
    expect(rowTexts(rows[0] as HTMLTableRowElement)[2]).toBe('5.39%');
    expect(rowTexts(rows[4] as HTMLTableRowElement)[2]).toBe('6.13%');
  });

  it('renders the annual Cumulative Operating Distributions schedule', () => {
    render(<OwnerReturnSchedule results={RESULTS} />);

    const rows = screen.getAllByRole('row').slice(1);
    expect(rowTexts(rows[0] as HTMLTableRowElement)[3]).toBe('$250,000');
    expect(rowTexts(rows[4] as HTMLTableRowElement)[3]).toBe('$1,175,947');
  });

  it('shows the Y3 IO-expiry drop in Levered CoC clearly', () => {
    render(<OwnerReturnSchedule results={RESULTS} />);

    const rows = screen.getAllByRole('row').slice(1);
    const y2 = Number.parseFloat(rowTexts(rows[1] as HTMLTableRowElement)[1]);
    const y3 = Number.parseFloat(rowTexts(rows[2] as HTMLTableRowElement)[1]);
    expect(y3).toBeLessThan(y2);
  });

  it('never reads the sale-inclusive terminal cash flow for the final row', () => {
    render(<OwnerReturnSchedule results={RESULTS} />);

    const rows = screen.getAllByRole('row').slice(1);
    const finalRowText = rowTexts(rows[4] as HTMLTableRowElement);
    // levered_cash_flows[5] (4,951,644.71) and unlevered_cash_flows[5]
    // (11,058,771.95) must never appear anywhere in the final row.
    expect(finalRowText.join(' ')).not.toContain('4,951,644');
    expect(finalRowText.join(' ')).not.toContain('11,058,771');
    expect(finalRowText[1]).toBe('5.61%'); // recurring-only Levered CoC
  });

  it('displays N/A for null Levered CoC and Year 1 Debt Yield, never 0.00%', () => {
    const zeroEquityResults: AcquisitionResults = {
      ...RESULTS,
      levered_cash_on_cash_by_year: [null, null, null, null, null],
      year_1_debt_yield: null,
    };

    render(<OwnerReturnSchedule results={zeroEquityResults} />);

    const rows = screen.getAllByRole('row').slice(1);
    for (const row of rows) {
      expect(rowTexts(row as HTMLTableRowElement)[1]).toBe('N/A');
    }
    expect(screen.queryByText('0.00%')).toBeNull();
  });

  it('renders negative Levered CoC and negative Cumulative Operating Distributions clearly', () => {
    const negativeResults: AcquisitionResults = {
      ...RESULTS,
      levered_cash_on_cash_by_year: [-0.05, -0.03, -0.01, 0.02, 0.04],
      cumulative_operating_distributions_by_year: [
        -100_000, -200_000, -150_000, -50_000, 50_000,
      ],
    };

    render(<OwnerReturnSchedule results={negativeResults} />);

    const rows = screen.getAllByRole('row').slice(1);
    expect(rowTexts(rows[0] as HTMLTableRowElement)[1]).toBe('-5.00%');
    expect(rowTexts(rows[0] as HTMLTableRowElement)[3]).toBe('-$100,000');
    expect(rowTexts(rows[1] as HTMLTableRowElement)[3]).toBe('-$200,000');
  });

  it('renders exactly one row for a one-year hold', () => {
    const oneYearResults: AcquisitionResults = {
      ...RESULTS,
      annual_debt_service: [386_511.57],
      levered_cash_on_cash_by_year: [0.0384],
      unlevered_cash_yield_by_year: [0.0539],
      cumulative_operating_distributions_by_year: [163_488.43],
      year_1_debt_yield: 0.1,
    };

    render(<OwnerReturnSchedule results={oneYearResults} />);

    const rows = screen.getAllByRole('row').slice(1);
    expect(rows.length).toBe(1);
    expect(rowTexts(rows[0] as HTMLTableRowElement)).toEqual([
      '1',
      '3.84%',
      '5.39%',
      '$163,488',
    ]);
  });
});
