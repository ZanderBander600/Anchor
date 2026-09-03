import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { OperatingStatementTable } from './OperatingStatementTable';
import type { AcquisitionResults, OperatingProjection } from '../types';

afterEach(() => {
  cleanup();
});

/** A 3-year hold with distinguishable values at every index, so a
 * transposed or off-by-one column shows up as a wrong cell rather than a
 * coincidental match. Mirrors CashFlowTable.test.tsx's RESULTS convention. */
const OPERATING_PROJECTION: OperatingProjection = {
  gross_potential_rent_by_year: [800_000, 824_000, 848_720],
  other_income_by_year: [20_000, 20_600, 21_218],
  vacancy_credit_loss_by_year: [40_000, 41_200, 42_436],
  effective_gross_income_by_year: [780_000, 803_400, 827_502],
  property_taxes_by_year: [60_000, 61_800, 63_654],
  insurance_by_year: [20_000, 20_600, 21_218],
  utilities_by_year: [25_000, 25_750, 26_522.5],
  repairs_maintenance_by_year: [20_000, 20_600, 21_218],
  other_operating_expenses_by_year: [16_000, 16_480, 16_974.4],
  management_fee_by_year: [39_000, 40_170, 41_375.1],
  total_operating_expenses_by_year: [180_000, 185_400, 190_962],
  noi_by_year: [600_000, 618_000, 636_540],
  exit_noi: 655_636.2,
  going_in_cap_rate: 0.06,
};

const RESULTS: AcquisitionResults = {
  going_in_cap_rate: 0.06,
  loan_amount: 6_000_000,
  acquisition_costs: 200_000,
  financing_fee: 60_000,
  initial_equity: 4_260_000,
  monthly_debt_service: 32_209.3,
  annual_debt_service: [300_000, 300_000, 386_511.57],
  remaining_loan_balance: 5_720_615.68,
  noi_by_year: [600_000, 618_000, 636_540],
  capex_by_year: [50_000, 50_000, 50_000],
  exit_noi: 655_636.2,
  exit_value: 10_700_991.46,
  disposition_costs: 267_524.79,
  net_sale_proceeds: 4_712_850.99,
  unlevered_cash_flows: [-10_200_000, 550_000, 568_000, 11_000_000],
  levered_cash_flows: [-4_260_000, 250_000, 268_000, 4_900_000],
  unlevered_irr: 0.06,
  levered_irr: 0.07,
  equity_multiple: 1.3,
  dscr_by_year: [2.0, 2.06, 1.65],
  headline_dscr: 2.0,
  min_dscr: 1.65,
};

function rowByLabel(label: string): HTMLTableRowElement {
  const cell = screen.getByText(label);
  return cell.closest('tr') as HTMLTableRowElement;
}

/** The row's per-year value cells only -- the first `<td>` is the line-item
 * label itself, not a year value. */
function cellTexts(row: HTMLTableRowElement): string[] {
  return Array.from(row.querySelectorAll('td'))
    .slice(1)
    .map((cell) => cell.textContent ?? '');
}

describe('OperatingStatementTable', () => {
  it('renders one column per hold-period year, using noi_by_year length as H', () => {
    render(
      <OperatingStatementTable operatingProjection={OPERATING_PROJECTION} results={RESULTS} />,
    );

    expect(screen.getByText('Year 1')).toBeTruthy();
    expect(screen.getByText('Year 2')).toBeTruthy();
    expect(screen.getByText('Year 3')).toBeTruthy();
    expect(screen.queryByText('Year 4')).toBeNull();
  });

  it('renders Gross Potential Rent from the operating projection, not results', () => {
    render(
      <OperatingStatementTable operatingProjection={OPERATING_PROJECTION} results={RESULTS} />,
    );

    const cells = cellTexts(rowByLabel('Gross Potential Rent'));
    expect(cells).toEqual(['$800,000', '$824,000', '$848,720']);
  });

  it('renders Net Operating Income matching noi_by_year exactly', () => {
    render(
      <OperatingStatementTable operatingProjection={OPERATING_PROJECTION} results={RESULTS} />,
    );

    const cells = cellTexts(rowByLabel('Net Operating Income'));
    expect(cells).toEqual(['$600,000', '$618,000', '$636,540']);
  });

  it('renders deduction lines parenthesized', () => {
    render(
      <OperatingStatementTable operatingProjection={OPERATING_PROJECTION} results={RESULTS} />,
    );

    const cells = cellTexts(rowByLabel('Less: Vacancy & Credit Loss'));
    expect(cells[0]).toBe('($40,000)');
  });

  it('renders CapEx Reserve and Debt Service from results, sliced to the hold period', () => {
    render(
      <OperatingStatementTable operatingProjection={OPERATING_PROJECTION} results={RESULTS} />,
    );

    expect(cellTexts(rowByLabel('CapEx Reserve'))).toEqual(['($50,000)', '($50,000)', '($50,000)']);
    expect(cellTexts(rowByLabel('Debt Service'))).toEqual(['($300,000)', '($300,000)', '($386,512)']);
  });

  it('renders Levered Cash Flow using Years 1..H, excluding the terminal Year 0 entry', () => {
    render(
      <OperatingStatementTable operatingProjection={OPERATING_PROJECTION} results={RESULTS} />,
    );

    // levered_cash_flows = [-4_260_000, 250_000, 268_000, 4_900_000]; index 0
    // is the Year-0 equity outlay, never shown in an operating statement.
    const cells = cellTexts(rowByLabel('Levered Cash Flow'));
    expect(cells).toEqual(['$250,000', '$268,000', '$4,900,000']);
  });

  it('shows the exit NOI as a sale-only note distinct from the noi_by_year table', () => {
    render(
      <OperatingStatementTable operatingProjection={OPERATING_PROJECTION} results={RESULTS} />,
    );

    expect(screen.getByText(/Exit NOI \(Year 4, sale-only\)/)).toBeTruthy();
    expect(screen.getByText(/\$655,636/)).toBeTruthy();
  });

  it('never shows current_noi, occupancy, or noi_growth labels', () => {
    render(
      <OperatingStatementTable operatingProjection={OPERATING_PROJECTION} results={RESULTS} />,
    );

    expect(screen.queryByText(/current noi/i)).toBeNull();
    expect(screen.queryByText(/occupancy/i)).toBeNull();
    expect(screen.queryByText(/noi growth/i)).toBeNull();
  });
});
