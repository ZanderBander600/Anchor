/**
 * D5.6A -- Lease-Level results presentation.
 *
 * D5.6 proved the figures were right. This gate changed only how they are
 * grouped and labelled, so the tests fall into two halves:
 *
 * 1. **The new presentation is actually there** -- the leasing/financing split,
 *    a single NOI row, the hold period and the Forward 12 valuation window told
 *    apart, and a label on the sale.
 * 2. **Nothing financial moved.** Every rendered figure, in both views and in
 *    the summary, is checked against the authoritative response field it came
 *    from. That is a stronger claim than a before/after snapshot: a snapshot
 *    would only prove this render matches the last one, whereas this proves the
 *    render matches the engine, which is what a presentation change must not
 *    disturb.
 *
 * The period grouping is the one part of this gate that could have introduced a
 * calculation, so it gets the most attention. Which months are forward months
 * is `is_forward_exit_month` on the response and nothing else -- never the hold
 * period times twelve, never the last twelve array entries. Those two mutants
 * are killed structurally in `modeDispatch.architecture.test.ts` and
 * behaviourally here, by moving the flags somewhere the arithmetic would not
 * follow.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import { analyzeLeaseLevelAcquisition, getDeal, listDeals } from './api';
import { formatCurrency, formatMultiple, formatPercent } from './format';
import { formatSquareFeet } from './leaseLevelFormat';
import type { LeaseLevelAcquisitionResults } from './leaseLevelTypes';
import { savedDeal } from './hiddenIssuesFixture';
import fixture from './leaseLevelResultsFixture.json';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    analyzeLeaseLevelAcquisition: vi.fn(),
    getDeal: vi.fn(),
    listDeals: vi.fn(),
  };
});

const mockAnalyze = vi.mocked(analyzeLeaseLevelAcquisition);
const mockGetDeal = vi.mocked(getDeal);
const mockListDeals = vi.mocked(listDeals);

const HEALTHY = fixture.healthy as unknown as LeaseLevelAcquisitionResults;
const MONTHS = HEALTHY.monthly_projection.months;
const HOLD_YEARS = HEALTHY.annual_projection.noi_by_year.length;

beforeEach(() => {
  vi.clearAllMocks();
  mockListDeals.mockResolvedValue([savedDeal()]);
  mockGetDeal.mockResolvedValue(savedDeal());
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

async function analyze(analysis: LeaseLevelAcquisitionResults = HEALTHY) {
  mockAnalyze.mockResolvedValue(analysis);
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText('Fulton Exchange');
  await user.click(screen.getByText('Fulton Exchange'));
  await waitFor(() => {
    expect(screen.getByRole('tablist', { name: 'Lease-Level sections' })).toBeTruthy();
  });
  await user.click(screen.getByRole('button', { name: /^Analyz/i }));
  await waitFor(() => {
    expect(mockAnalyze).toHaveBeenCalled();
  });
  return user;
}

function resultsPanel(): HTMLElement {
  return document.getElementById('lease-level-panel-results') as HTMLElement;
}

function statement(): HTMLElement {
  return document.querySelector('.lease-level-statement-table') as HTMLElement;
}

async function openStatement(
  user: ReturnType<typeof userEvent.setup>,
  period: 'Monthly' | 'Annual',
) {
  await user.click(within(resultsPanel()).getByRole('tab', { name: 'Operating Statement' }));
  await user.click(within(resultsPanel()).getByRole('tab', { name: period }));
}

function rowHeader(label: string): HTMLElement {
  const found = Array.from(statement().querySelectorAll('th[scope="row"]')).find(
    (cell) => cell.textContent === label,
  );
  if (found === undefined) {
    throw new Error(`No statement row labelled ${label}`);
  }
  return found as HTMLElement;
}

function rowValues(label: string): string[] {
  const row = rowHeader(label).closest('tr') as HTMLElement;
  return Array.from(row.querySelectorAll('td')).map((cell) => cell.textContent ?? '');
}

/** The row groups, in document order: one `tbody` each, titled or not. */
function bands(): { title: string; rows: string[] }[] {
  return Array.from(statement().querySelectorAll('tbody')).map((group) => ({
    title: group.querySelector('th[scope="rowgroup"]')?.textContent ?? '',
    rows: Array.from(group.querySelectorAll('th[scope="row"]')).map(
      (cell) => cell.textContent ?? '',
    ),
  }));
}

function bandNamed(title: string): { title: string; rows: string[] } {
  const found = bands().find((band) => band.title === title);
  if (found === undefined) {
    throw new Error(`No band titled ${title}. Saw: ${bands().map((b) => b.title).join(', ')}`);
  }
  return found;
}

/** The period column headers: the last head row is always the periods. */
function periodHeaders(): HTMLElement[] {
  const rows = statement().querySelectorAll('thead tr');
  return Array.from(rows[rows.length - 1].querySelectorAll('th')) as HTMLElement[];
}

function periodBands(): { label: string; span: number; forward: boolean }[] {
  const band = statement().querySelector('thead tr.lease-level-statement-periods');
  if (band === null) {
    return [];
  }
  return Array.from(band.querySelectorAll('th[scope="colgroup"]')).map((cell) => ({
    label: cell.textContent ?? '',
    span: Number(cell.getAttribute('colspan')),
    forward: cell.classList.contains('lease-level-statement-forward'),
  }));
}

// =============================================================================
// 1. Net Sale Proceeds to Equity (M1)
// =============================================================================

describe('net sale proceeds', () => {
  it('names the equity the proceeds actually reach (M1)', async () => {
    await analyze();
    const panel = within(resultsPanel());

    expect(panel.getByText('Net Sale Proceeds to Equity')).toBeTruthy();
    // The bare label is gone from the summary: the figure is after disposition
    // costs and after repaying the loan, and "Net Sale Proceeds" left an
    // analyst to guess which of those had already happened.
    expect(panel.queryByText('Net Sale Proceeds')).toBeNull();
  });

  it('changes only the label, never the value', async () => {
    await analyze();
    const summary = within(resultsPanel());
    const label = summary.getByText('Net Sale Proceeds to Equity');
    const value = (label.closest('.lease-level-metric') as HTMLElement).querySelector('dd');
    expect(value?.textContent).toBe(formatCurrency(HEALTHY.results.net_sale_proceeds));
  });
});

// =============================================================================
// 2. One NOI row (M2)
// =============================================================================

describe('net operating income hierarchy', () => {
  it.each(['Annual', 'Monthly'] as const)(
    'names NOI once in the %s view, not as a heading and a row (M2)',
    async (period) => {
      const user = await analyze();
      await openStatement(user, period);

      const occurrences = Array.from(statement().querySelectorAll('th')).filter(
        (cell) => cell.textContent === 'Net Operating Income',
      );
      expect(occurrences).toHaveLength(1);
      // The one that survived is the row carrying the figures, not a band.
      expect(occurrences[0].getAttribute('scope')).toBe('row');
      expect(bands().map((band) => band.title)).not.toContain('Net Operating Income');
    },
  );

  it('keeps the NOI row visually prominent', async () => {
    const user = await analyze();
    await openStatement(user, 'Annual');

    const row = rowHeader('Net Operating Income').closest('tr') as HTMLElement;
    expect(row.classList.contains('lease-level-statement-noi')).toBe(true);
    expect(row.classList.contains('operating-statement-emphasis')).toBe(true);
  });
});

// =============================================================================
// 3. Leasing & Capital Costs vs Financing (M3, M4, M5)
// =============================================================================

describe('below-NOI grouping', () => {
  it('groups leasing capital together in the annual view', async () => {
    const user = await analyze();
    await openStatement(user, 'Annual');

    expect(bandNamed('Leasing & Capital Costs').rows).toEqual([
      'Tenant Improvements',
      'Leasing Commissions',
      'CapEx Reserve',
    ]);
  });

  it('gives debt service its own Financing band (M3)', async () => {
    const user = await analyze();
    await openStatement(user, 'Annual');

    expect(bandNamed('Financing').rows).toEqual(['Debt Service']);
    // Financing is a cost of how the building was bought, not of keeping it
    // let. Sharing a band made an unlevered read of the property harder.
    expect(bandNamed('Leasing & Capital Costs').rows).not.toContain('Debt Service');
    // And it is still not an operating expense, which is the older and worse
    // mistake this grouping could have invited.
    expect(bandNamed('Operating Expenses').rows).not.toContain('Debt Service');
  });

  it('keeps both bands below NOI, where D4 puts them', async () => {
    const user = await analyze();
    await openStatement(user, 'Annual');

    const rows = Array.from(statement().querySelectorAll('tbody tr'));
    const indexOf = (label: string) =>
      rows.findIndex((row) => row.querySelector('th')?.textContent === label);

    const noi = indexOf('Net Operating Income');
    for (const below of ['Leasing & Capital Costs', 'Financing', 'Debt Service', 'CapEx Reserve']) {
      expect(indexOf(below), `${below} sits above NOI`).toBeGreaterThan(noi);
    }
  });

  it('shows leasing capital monthly and fabricates no financing (M4, M5)', async () => {
    const user = await analyze();
    await openStatement(user, 'Monthly');

    expect(bandNamed('Leasing & Capital Costs').rows).toEqual([
      'Tenant Improvements',
      'Leasing Commissions',
    ]);

    // There is no canonical monthly debt service and no canonical monthly
    // capex. Showing either would mean dividing an annual figure by twelve --
    // a schedule the engine never computed and the loan does not follow.
    const labels = Array.from(statement().querySelectorAll('th[scope="row"]')).map(
      (cell) => cell.textContent,
    );
    expect(labels).not.toContain('Debt Service');
    expect(labels).not.toContain('CapEx Reserve');
    expect(bands().map((band) => band.title)).not.toContain('Financing');
  });
});

// =============================================================================
// 4. Hold period vs the Forward 12 valuation window (M6-M10, M13)
// =============================================================================

/** The forward months as the *response* classifies them. Every expectation
 * below is measured against this, never against a count of anything. */
const FORWARD_LABELS = MONTHS.filter((month) => month.is_forward_exit_month);
const HOLD_LABELS = MONTHS.filter((month) => !month.is_forward_exit_month);

describe('the forward valuation window', () => {
  it('is classified by the response, month for month (M8, M9)', async () => {
    const user = await analyze();
    await openStatement(user, 'Monthly');

    const headers = periodHeaders();
    expect(headers).toHaveLength(MONTHS.length);

    // Every column agrees with the flag the backend put on that month: no hold
    // month styled as forward, no forward month styled as hold.
    MONTHS.forEach((month, index) => {
      expect(
        headers[index].classList.contains('lease-level-statement-forward'),
        `${month.month_start} classified wrongly`,
      ).toBe(month.is_forward_exit_month);
    });
  });

  it('bands the columns into hold period and Forward 12 (M6, M7)', async () => {
    const user = await analyze();
    await openStatement(user, 'Monthly');

    const [hold, forward] = periodBands();
    expect(hold.label).toContain('Hold Period');
    expect(hold.forward).toBe(false);
    expect(hold.span).toBe(HOLD_LABELS.length);

    expect(forward.label).toContain('Forward 12 Months');
    expect(forward.label).toContain('Used for Exit Valuation');
    expect(forward.forward).toBe(true);
    expect(forward.span).toBe(FORWARD_LABELS.length);
  });

  it('marks the sale at the first forward month, and only there (M13)', async () => {
    const user = await analyze();
    await openStatement(user, 'Monthly');

    const boundaries = periodHeaders()
      .map((cell, index) => ({ cell, index }))
      .filter(({ cell }) => cell.classList.contains('lease-level-statement-boundary'));

    expect(boundaries).toHaveLength(1);
    expect(boundaries[0].cell.textContent).toContain(
      // The month the response says the forward window opens on.
      'Jan 2032',
    );
    expect(MONTHS[boundaries[0].index].is_forward_exit_month).toBe(true);
    expect(MONTHS[boundaries[0].index - 1].is_forward_exit_month).toBe(false);

    // The marker is a label, not a column: no extra header, no extra cell, no
    // month invented to hang it on.
    expect(periodHeaders()).toHaveLength(MONTHS.length);
    expect(rowValues('Net Operating Income')).toHaveLength(MONTHS.length);
    expect(
      Array.from(statement().querySelectorAll('td')).some((cell) =>
        (cell.textContent ?? '').includes('Sale'),
      ),
    ).toBe(false);
  });

  it('says "Sale / Hold End" in words, not only in colour', async () => {
    const user = await analyze();
    await openStatement(user, 'Monthly');

    expect(within(statement()).getByText('Sale / Hold End')).toBeTruthy();
    // The boundary column carries its own textual note, so a screen reader
    // moving across the header hears where the ownership period ended.
    const boundary = periodHeaders().find((cell) =>
      cell.classList.contains('lease-level-statement-boundary'),
    ) as HTMLElement;
    expect(boundary.textContent).toContain('sale and hold end');
    expect(boundary.textContent).toContain('exit valuation');
  });

  it('keeps ordinary month labels, and the row labels sticky', async () => {
    const user = await analyze();
    await openStatement(user, 'Monthly');

    const headers = periodHeaders().map((cell) => cell.textContent ?? '');
    expect(headers[0]).toBe('Jan 2027');
    // A forward month is still just a month. Renaming it would hide when it is.
    expect(headers[headers.length - 1]).toContain('Dec 2032');

    // The line-item column is the band row's corner cell, spanning both header
    // rows, so it stays put while the periods scroll under it.
    const corner = statement().querySelector('.lease-level-statement-corner') as HTMLElement;
    expect(corner.textContent).toBe('Line Item');
    expect(corner.getAttribute('rowspan')).toBe('2');
    expect(rowHeader('Net Operating Income').getAttribute('scope')).toBe('row');
  });

  it('explains what the forward months are for', async () => {
    const user = await analyze();
    await openStatement(user, 'Monthly');

    const panel = within(resultsPanel());
    expect(panel.getByText(/notionally sold at the end of the hold period/i)).toBeTruthy();
    expect(panel.getByText(/determine the Exit NOI capitalised at that sale/i)).toBeTruthy();
    expect(panel.getByText(/not another year of ownership/i)).toBeTruthy();
  });
});

describe('the annual view', () => {
  it('shows the hold years and no forward year (M10)', async () => {
    const user = await analyze();
    await openStatement(user, 'Annual');

    const headers = periodHeaders().map((cell) => cell.textContent ?? '');
    expect(headers).toEqual([
      'Line Item',
      ...Array.from({ length: HOLD_YEARS }, (_, index) => `Year ${index + 1}`),
    ]);

    // The forward window is a valuation period, not a year of ownership.
    // Year 6 on a five-year hold would be exactly the reading D4 avoids.
    expect(headers).not.toContain(`Year ${HOLD_YEARS + 1}`);
    expect(rowValues('Net Operating Income')).toHaveLength(HOLD_YEARS);
    // And no period band, because one group is not a grouping.
    expect(periodBands()).toEqual([]);
  });

  it('keeps forward leasing costs out of the hold-period rows (M12)', async () => {
    const user = await analyze();
    await openStatement(user, 'Annual');

    // The annual TI and LC rows are the hold-period arrays exactly. The
    // backend oracle proves those exclude the forward window; this proves the
    // UI renders the excluding arrays rather than quietly adding to them.
    expect(rowValues('Tenant Improvements')).toEqual(
      HEALTHY.annual_projection.tenant_improvements_by_year.map(formatCurrency),
    );
    expect(rowValues('Leasing Commissions')).toEqual(
      HEALTHY.annual_projection.leasing_commissions_by_year.map(formatCurrency),
    );
    expect(rowValues('Tenant Improvements')).toHaveLength(HOLD_YEARS);
  });
});

// =============================================================================
// 5. Exit copy
// =============================================================================

describe('exit copy', () => {
  it('connects Exit NOI to the forward window on the statement', async () => {
    await analyze();
    expect(
      within(resultsPanel()).getByText(/Forward 12-month NOI used for exit valuation/i),
    ).toBeTruthy();
  });

  it('states exit window leasing costs correctly', async () => {
    await analyze();
    const note = within(resultsPanel()).getByText(
      /TI and leasing commissions falling in the Forward 12 valuation period/i,
    );
    // They are disclosed and excluded. Saying they reduce Exit NOI would be
    // false: Exit NOI is an NOI, and leasing capital sits below it.
    expect(note.textContent).toContain('Excluded from Exit NOI');
    expect(note.textContent).toContain('hold-period cash flow');
    expect(note.textContent).not.toMatch(/reduce|net of|deducted from Exit NOI/i);
  });
});

// =============================================================================
// 6. Nothing financial moved (M11, M14)
// =============================================================================

/** A contra line as it is shown: the magnitude the wire carries, with a
 * display sign in front of it. The magnitude itself is untouched, which is the
 * point -- `contra(x)` is `formatCurrency(x)` plus a character, never
 * `formatCurrency(-x)`. */
function contra(value: number): string {
  return value > 0 ? `-${formatCurrency(value)}` : formatCurrency(value);
}

/** Every statement row, paired with the response array it must equal. */
function annualExpectations(): [string, string[]][] {
  const annual = HEALTHY.annual_projection;
  const results = HEALTHY.results;
  return [
    ['Contractual Base Rent', annual.contractual_base_rent_by_year.map(formatCurrency)],
    ['Less: Free Rent', annual.free_rent_by_year.map(contra)],
    ['Cash Base Rent', annual.cash_base_rent_by_year.map(formatCurrency)],
    ['Expense Recoveries', annual.expense_recovery_by_year.map(formatCurrency)],
    ['Other Income', annual.other_income_by_year.map(formatCurrency)],
    ['Less: Credit Loss', annual.credit_loss_by_year.map(contra)],
    ['Effective Gross Income', annual.effective_gross_income_by_year.map(formatCurrency)],
    ['Property Taxes', annual.property_taxes_by_year.map(formatCurrency)],
    ['Insurance', annual.insurance_by_year.map(formatCurrency)],
    ['Utilities', annual.utilities_by_year.map(formatCurrency)],
    ['Repairs & Maintenance', annual.repairs_maintenance_by_year.map(formatCurrency)],
    ['Other Operating Expenses', annual.other_operating_expenses_by_year.map(formatCurrency)],
    ['Fixed Operating Expenses', annual.fixed_operating_expenses_by_year.map(formatCurrency)],
    ['Management Fee', annual.management_fee_by_year.map(formatCurrency)],
    ['Total Operating Expenses', annual.total_operating_expenses_by_year.map(formatCurrency)],
    ['Net Operating Income', annual.noi_by_year.map(formatCurrency)],
    ['Tenant Improvements', annual.tenant_improvements_by_year.map(formatCurrency)],
    ['Leasing Commissions', annual.leasing_commissions_by_year.map(formatCurrency)],
    ['CapEx Reserve', results.capex_by_year.slice(0, HOLD_YEARS).map(formatCurrency)],
    ['Debt Service', results.annual_debt_service.slice(0, HOLD_YEARS).map(formatCurrency)],
    ['Occupied Area at Year End', annual.occupied_area_at_year_end.map(formatSquareFeet)],
    ['Vacant Area at Year End', annual.vacant_area_at_year_end.map(formatSquareFeet)],
    [
      'Physical Occupancy at Year End',
      annual.physical_occupancy_at_year_end.map((value) => formatPercent(value)),
    ],
    [
      'Average Physical Occupancy',
      annual.average_physical_occupancy_over_year.map((value) => formatPercent(value)),
    ],
  ];
}

function monthlyExpectations(): [string, string[]][] {
  const monthly = HEALTHY.monthly_projection;
  return [
    ['Contractual Base Rent', monthly.contractual_base_rent.map(formatCurrency)],
    ['Less: Free Rent', monthly.free_rent.map(contra)],
    ['Cash Base Rent', monthly.cash_base_rent.map(formatCurrency)],
    ['Expense Recoveries', monthly.expense_recovery.map(formatCurrency)],
    ['Other Income', monthly.other_income.map(formatCurrency)],
    ['Less: Credit Loss', monthly.credit_loss.map(contra)],
    ['Effective Gross Income', monthly.effective_gross_income.map(formatCurrency)],
    ['Property Taxes', monthly.property_taxes.map(formatCurrency)],
    ['Insurance', monthly.insurance.map(formatCurrency)],
    ['Utilities', monthly.utilities.map(formatCurrency)],
    ['Repairs & Maintenance', monthly.repairs_maintenance.map(formatCurrency)],
    ['Other Operating Expenses', monthly.other_operating_expenses.map(formatCurrency)],
    ['Fixed Operating Expenses', monthly.fixed_operating_expenses.map(formatCurrency)],
    ['Management Fee', monthly.management_fee.map(formatCurrency)],
    ['Total Operating Expenses', monthly.total_operating_expenses.map(formatCurrency)],
    ['Net Operating Income', monthly.noi.map(formatCurrency)],
    ['Tenant Improvements', monthly.tenant_improvements.map(formatCurrency)],
    ['Leasing Commissions', monthly.leasing_commissions.map(formatCurrency)],
    ['Occupied Area', monthly.occupied_area_sf.map(formatSquareFeet)],
    ['Vacant Area', monthly.vacant_area_sf.map(formatSquareFeet)],
    ['Physical Occupancy', monthly.physical_occupancy.map((value) => formatPercent(value))],
  ];
}

describe('the regrouping moved no number (M14)', () => {
  it('renders every annual row as its response array, cell for cell', async () => {
    const user = await analyze();
    await openStatement(user, 'Annual');

    for (const [label, expected] of annualExpectations()) {
      expect(rowValues(label), label).toEqual(expected);
    }
  });

  it('renders every monthly row as its response array, cell for cell', async () => {
    const user = await analyze();
    await openStatement(user, 'Monthly');

    for (const [label, expected] of monthlyExpectations()) {
      expect(rowValues(label), label).toEqual(expected);
    }
  });

  it('renders every summary metric as its response field', async () => {
    await analyze();
    const panel = within(resultsPanel());
    const results = HEALTHY.results;

    const expected: [string, string][] = [
      ['Levered IRR', formatPercent(results.levered_irr)],
      ['Unlevered IRR', formatPercent(results.unlevered_irr)],
      ['Equity Multiple', formatMultiple(results.equity_multiple)],
      ['Going-In Cap Rate', formatPercent(results.going_in_cap_rate)],
      ['Year 1 Debt Yield', formatPercent(results.year_1_debt_yield)],
      ['Loan Amount', formatCurrency(results.loan_amount)],
      ['Exit NOI', formatCurrency(results.exit_noi)],
      ['Exit Value', formatCurrency(results.exit_value)],
      ['Disposition Costs', formatCurrency(results.disposition_costs)],
      ['Net Sale Proceeds to Equity', formatCurrency(results.net_sale_proceeds)],
      [
        'Exit Window Leasing Costs',
        formatCurrency(HEALTHY.annual_projection.exit_window_leasing_costs),
      ],
      ['Initial Equity', formatCurrency(results.initial_equity)],
      ['Acquisition Costs', formatCurrency(results.acquisition_costs)],
      ['Financing Fee', formatCurrency(results.financing_fee)],
      ['Rentable Area', formatSquareFeet(HEALTHY.monthly_projection.rentable_area_sf)],
    ];

    for (const [label, value] of expected) {
      const metric = panel.getByText(label).closest('.lease-level-metric') as HTMLElement;
      expect(metric.querySelector('dd')?.textContent, label).toBe(value);
    }
  });

  it('reads Exit NOI off the response, never off the forward columns (M11)', async () => {
    // The tile and the forward months agree financially, so agreement proves
    // nothing. Move the tile's own field and leave the monthly NOI alone: a
    // component that totalled the columns it had just drawn would show the old
    // figure, and a component that reads the response shows the new one.
    const mutant = structuredClone(HEALTHY) as LeaseLevelAcquisitionResults;
    (mutant.results as unknown as Record<string, number>).exit_noi = 777_777;

    await analyze(mutant);
    const panel = within(resultsPanel());
    const metric = panel.getByText('Exit NOI').closest('.lease-level-metric') as HTMLElement;
    expect(metric.querySelector('dd')?.textContent).toBe('$777,777');
  });
});

// =============================================================================
// 7. Contra revenue, the NOI break, and the sliding phase label
// =============================================================================

describe('contra revenue reads as a deduction', () => {
  it.each(['Annual', 'Monthly'] as const)(
    'shows a leading minus and keeps the Less: label in the %s view',
    async (period) => {
      const user = await analyze();
      await openStatement(user, period);

      for (const label of ['Less: Free Rent', 'Less: Credit Loss']) {
        const cells = rowValues(label);
        const nonZero = cells.filter((cell) => cell !== '$0');
        expect(nonZero.length, `${label} is all zero, so nothing is proved`).toBeGreaterThan(0);
        for (const cell of nonZero) {
          expect(cell, `${label} cell ${cell}`).toMatch(/^-\$/);
        }
        // Colour is the weakest cue and the first one lost -- to a printer, to
        // a screen reader, to anyone who does not see red. The word stays.
        expect(rowHeader(label).textContent).toContain('Less:');
      }
    },
  );

  it('marks the rows so the styling has something to hang on', async () => {
    const user = await analyze();
    await openStatement(user, 'Annual');

    for (const label of ['Less: Free Rent', 'Less: Credit Loss']) {
      const row = rowHeader(label).closest('tr') as HTMLElement;
      expect(row.classList.contains('lease-level-statement-contra'), label).toBe(true);
    }
  });

  it('leaves a zero as a zero, not as minus zero', async () => {
    const user = await analyze();
    await openStatement(user, 'Annual');

    // The fixture has a hold year with no free rent at all. `-$0` would be
    // nonsense, and is what a blanket prefix would have produced.
    const cells = rowValues('Less: Free Rent');
    expect(cells).toContain('$0');
    expect(cells).not.toContain('-$0');
  });

  it('does not repaint the operating expenses, which have a heading of their own', async () => {
    const user = await analyze();
    await openStatement(user, 'Annual');

    // Expenses sit under a band that says what they are, so they need no sign.
    // Only the contra lines inside the revenue block do.
    for (const label of ['Property Taxes', 'Management Fee', 'Tenant Improvements']) {
      const row = rowHeader(label).closest('tr') as HTMLElement;
      expect(row.classList.contains('lease-level-statement-contra'), label).toBe(false);
      for (const cell of rowValues(label)) {
        expect(cell, `${label} cell ${cell}`).not.toMatch(/^-/);
      }
    }
  });

  it('changes only the sign shown, never the magnitude', async () => {
    const user = await analyze();
    await openStatement(user, 'Annual');

    // The wire value is a positive magnitude and stays one: what changed is a
    // character in front of the formatted string, not the number behind it.
    expect(HEALTHY.annual_projection.free_rent_by_year[0]).toBeGreaterThan(0);
    expect(rowValues('Less: Free Rent')[0]).toBe(
      `-${formatCurrency(HEALTHY.annual_projection.free_rent_by_year[0])}`,
    );
  });
});

describe('net operating income stands on its own', () => {
  it.each(['Annual', 'Monthly'] as const)(
    'is not the last row of the expense block in the %s view',
    async (period) => {
      const user = await analyze();
      await openStatement(user, period);

      const row = rowHeader('Net Operating Income').closest('tr') as HTMLElement;
      const group = row.closest('tbody') as HTMLTableSectionElement;

      // Its own row group, with nothing else in it. Not the last line of the
      // expense block, in the markup or to the eye.
      expect(Array.from(group.querySelectorAll('th[scope="row"]'))).toHaveLength(1);
      expect(group.querySelector('th[scope="rowgroup"]')).toBeNull();
      expect(bandNamed('Operating Expenses').rows).not.toContain('Net Operating Income');
      expect(bandNamed('Operating Expenses').rows).toContain('Total Operating Expenses');

      // And it sits between the two, in the order an operating statement reads.
      const groups = Array.from(statement().querySelectorAll('tbody'));
      expect(groups.indexOf(group)).toBe(
        groups.findIndex(
          (candidate) =>
            candidate.querySelector('th[scope="rowgroup"]')?.textContent ===
            'Operating Expenses',
        ) + 1,
      );
    },
  );
});

describe('the phase label travels with its own band', () => {
  it('lives inside the band cell, which is what stops it at the next phase', async () => {
    const user = await analyze();
    await openStatement(user, 'Monthly');

    const band = statement().querySelector('thead tr.lease-level-statement-periods') as HTMLElement;
    const cells = Array.from(band.querySelectorAll('th[scope="colgroup"]'));

    // A sticky box cannot leave its containing block. The containing block for
    // each label is its own band cell, so the Hold Period label slides as far
    // as the sale and then goes with its band -- it can never cross into the
    // Forward 12 columns and mislabel them. That guarantee is structural, so
    // this asserts the structure: one label, inside its own cell, per band.
    for (const cell of cells) {
      const labels = cell.querySelectorAll('.lease-level-statement-period-label');
      expect(labels).toHaveLength(1);
      expect(labels[0].parentElement).toBe(cell);
    }
    expect(cells).toHaveLength(2);

    // The phase name leads the label, ahead of its note.
    const first = cells[0].querySelector('.lease-level-statement-period-label') as HTMLElement;
    expect(first.firstElementChild?.textContent).toBe('Hold Period');
    expect(first.textContent).toBe('Hold PeriodOwnership');

    // The sale marker is a sibling of the label, not part of it, so it stays
    // pinned at the band edge while the label travels.
    const sale = cells[0].querySelector('.lease-level-statement-sale') as HTMLElement;
    expect(sale.textContent).toBe('Sale / Hold End');
    expect(sale.parentElement).toBe(cells[0]);
  });
});
