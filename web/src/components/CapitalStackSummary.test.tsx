/**
 * Workstation polish pass -- the saved Capital Structure summary reads the
 * authored stack back, and says what each refinance repays and funds. It
 * shows no figure the analyst did not author.
 */

import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { CapitalStructure } from '../capitalTypes';
import { CapitalStackSummary } from './CapitalStackSummary';

afterEach(cleanup);

const STRUCTURE: CapitalStructure = {
  positions: [
    {
      position_id: 'sd-1',
      name: 'Replacement loan',
      position_class: 'senior_debt',
      priority: 1,
      scope: { kind: 'unit', unit_id: 'u-1' },
      funding: [
        {
          event_id: 'f-1',
          model_month: 24,
          sequence: 1,
          amount_rule: { kind: 'refinance_proceeds', capital_event_id: 'ev-1' },
        },
      ],
      terms: {
        kind: 'debt',
        interest_rate: 0.05,
        amortization: 30,
        io_period: 5,
        maturity_month: 144,
        fees: [],
        current_pay_rate: 0.05,
        pik_rate: 0,
      },
      shortfall_resolution: 'common_equity_contribution',
    },
    {
      position_id: 'mz-1',
      name: 'Mezz',
      position_class: 'mezzanine_debt',
      priority: 2,
      scope: { kind: 'unit', unit_id: 'u-1' },
      funding: [
        { event_id: 'f-2', model_month: 0, sequence: 1, amount_rule: { kind: 'fixed_amount', amount: 500000 } },
      ],
      terms: {
        kind: 'debt',
        interest_rate: 0.1,
        amortization: 30,
        io_period: 0,
        maturity_month: 120,
        fees: [],
        current_pay_rate: 0.1,
        pik_rate: 0,
      },
      shortfall_resolution: 'common_equity_contribution',
    },
  ],
  capital_events: [
    {
      event_id: 'ev-1',
      kind: 'refinance',
      scope: { kind: 'unit', unit_id: 'u-1' },
      timing: { model_month: 24, sequence: 1 },
      label: 'Year-2 refinance',
      retiring: [
        { kind: 'legacy_acquisition_loan', unit_id: 'u-1' },
        { kind: 'authored_position', position_id: 'mz-1' },
      ],
      replacement_position_id: 'sd-1',
      sizing: { fixed_cap: null, max_ltv: null, min_dscr: { min_dscr: 2 } },
      valuation: null,
      costs: [],
    },
  ],
};

function renderSummary() {
  render(<CapitalStackSummary structure={STRUCTURE} unitNames={{ 'u-1': 'This Deal' }} multiUnit={false} />);
  return screen.getByRole('region', { name: 'Saved capital structure' });
}

describe('the saved Capital Structure summary', () => {
  it('lists each position in saved order with its class, priority, scope, funding and terms', () => {
    const region = renderSummary();
    const rows = within(region).getAllByRole('row').slice(1);
    expect(rows.map((row) => within(row).getByRole('rowheader').textContent)).toEqual([
      'Replacement loanSenior Debt',
      'MezzMezzanine Debt',
    ]);
    const mezz = rows[1];
    expect(within(mezz).getByText('$500,000 at closing')).toBeTruthy();
    expect(within(mezz).getByText('10% rate · 30-yr amortization · no interest-only · matures month 120')).toBeTruthy();
    expect(within(mezz).getByText('2')).toBeTruthy();
    expect(within(mezz).getByText('This Deal')).toBeTruthy();
  });

  it('names the refinance a replacement loan is sized by, never an amount it did not author', () => {
    const region = renderSummary();
    const replacement = within(region).getAllByRole('row')[1];
    expect(within(replacement).getByText('Sized by “Year-2 refinance” at the end of Year 2')).toBeTruthy();
    expect(replacement.textContent).not.toMatch(/\$/);
  });

  it('says what each refinance repays and funds', () => {
    renderSummary();
    const events = screen.getByRole('list', { name: 'Refinances' });
    expect(within(events).getByText('Year-2 refinance')).toBeTruthy();
    expect(
      within(events).getByText('End of Year 2 · repays Acquisition loan, Mezz · funds Replacement loan · This Deal'),
    ).toBeTruthy();
  });

  it('labels every stacked fact for narrow screens', () => {
    const region = renderSummary();
    const cells = within(region).getAllByRole('cell');
    expect(new Set(cells.map((cell) => cell.getAttribute('data-label')))).toEqual(
      new Set(['Priority', 'Scope', 'Funding', 'Key terms']),
    );
  });
});
