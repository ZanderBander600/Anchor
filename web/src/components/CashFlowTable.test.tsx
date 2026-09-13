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
  levered_cash_on_cash_by_year: [0.01, 0.02, 0.03],
  unlevered_cash_yield_by_year: [0.04, 0.05, 0.06],
  cumulative_operating_distributions_by_year: [10, 20, 30],
  year_1_debt_yield: 0.07,
  // D6.7 widened the result contract. This suite renders no Capital Economics
  // and reads none of these fields: type-complete placeholders, not a case.
  tenant_improvements_by_year: [0, 0, 0],
  leasing_commissions_by_year: [0, 0, 0],
  closing_project_capital: 0,
  project_capital_by_year: [0, 0, 0],
  post_hold_project_capital: 0,
  owner_expenses_by_year: [0, 0, 0],
  property_cash_flow_by_year: [0, 0, 0],
  unlevered_owner_cash_flow_by_year: [0, 0, 0],
  levered_owner_cash_flow_by_year: [0, 0, 0],
  total_closing_uses: 0,
  total_closing_sources: 0,
  net_additional_equity_requirement_by_year: [0, 0, 0],
  total_equity_invested: 0,
  total_cash_returned: 0,
  total_profit: 0,
  unlevered_irr_status: 'defined',
  levered_irr_status: 'defined',
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
