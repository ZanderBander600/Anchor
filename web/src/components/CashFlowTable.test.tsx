import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render } from '@testing-library/react';
import { CashFlowTable } from './CashFlowTable';
import type { AcquisitionResults } from '../types';

afterEach(() => {
  cleanup();
});

/**
 * A 3-year hold with distinguishable values at every index, so a transposed
 * or off-by-one index shows up as a wrong cell rather than a coincidental
 * match.
 */
const RESULTS: AcquisitionResults = {
  going_in_cap_rate: 0.05,
  loan_amount: 1,
  acquisition_costs: 1,
  financing_fee: 1,
  initial_equity: 1,
  monthly_debt_service: 1,
  annual_debt_service: [11, 22, 33],
  remaining_loan_balance: 1,
  noi_by_year: [111, 222, 333],
  capex_by_year: [5, 6, 7],
  exit_noi: 1,
  exit_value: 1,
  disposition_costs: 1,
  net_sale_proceeds: 1,
  unlevered_cash_flows: [-999, 100, 200, 9999],
  levered_cash_flows: [-888, 50, 60, 8888],
  unlevered_irr: 0.1,
  levered_irr: 0.1,
  equity_multiple: 1.1,
  dscr_by_year: [1.1, 2.2, 3.3],
  headline_dscr: 1.1,
  min_dscr: 1.1,
};

function rowTexts(row: HTMLTableRowElement): string[] {
  return Array.from(row.querySelectorAll('td')).map((cell) => cell.textContent ?? '');
}

describe('CashFlowTable indexing', () => {
  it('aligns Year 0 with cash-flow index 0 and no NOI/ADS/DSCR', () => {
    const { container } = render(<CashFlowTable results={RESULTS} />);
    const rows = container.querySelectorAll('tbody tr');

    expect(rowTexts(rows[0] as HTMLTableRowElement)).toEqual([
      '0',
      '—',
      '—',
      '—',
      '—',
      '-$999',
      '-$888',
    ]);
  });

  it('aligns Year 1 with NOI/CapEx/ADS/DSCR index 0 and cash-flow index 1', () => {
    const { container } = render(<CashFlowTable results={RESULTS} />);
    const rows = container.querySelectorAll('tbody tr');

    expect(rowTexts(rows[1] as HTMLTableRowElement)).toEqual([
      '1',
      '$111',
      '$5',
      '$11',
      '1.10x',
      '$100',
      '$50',
    ]);
  });

  it('aligns the final hold year with the last NOI/CapEx/ADS/DSCR entry and its cash-flow index', () => {
    const { container } = render(<CashFlowTable results={RESULTS} />);
    const rows = container.querySelectorAll('tbody tr');
    const finalRow = rows[rows.length - 1] as HTMLTableRowElement;

    expect(rowTexts(finalRow)).toEqual([
      '3',
      '$333',
      '$7',
      '$33',
      '3.30x',
      '$9,999',
      '$8,888',
    ]);
  });

  it('renders exactly one row per hold year plus the Year 0 row', () => {
    const { container } = render(<CashFlowTable results={RESULTS} />);
    const rows = container.querySelectorAll('tbody tr');

    expect(rows.length).toBe(RESULTS.annual_debt_service.length + 1);
  });
});
