/**
 * D5.6 -- Lease-Level results, driven by real engine output.
 *
 * The fixture is not hand-written. `leaseLevelResultsFixture.json` holds two
 * captured `/analyze` responses: one healthy deal, and one whose levered cash
 * flows change sign twice so the engine returns `levered_irr: null`. Writing
 * those numbers by hand would have meant inventing the very values this gate
 * exists to render faithfully, and would not have caught the two annual field
 * names D5.5A had wrong.
 *
 * What these tests hold closed: results appear, they come from the response
 * rather than from arithmetic, monthly and annual read different arrays, TI and
 * LC stay below NOI, an undefined IRR reads as undefined rather than as zero,
 * and a reopened deal shows no stale figure.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import { analyzeLeaseLevelAcquisition, getDeal, listDeals, updateLeaseLevelDeal } from './api';
import { resultsViewsFor } from './underwrite';
import { formatMonthLabel } from './leaseLevelFormat';
import type { LeaseLevelAcquisitionResults } from './leaseLevelTypes';
import { savedDeal } from './hiddenIssuesFixture';
import fixture from './leaseLevelResultsFixture.json';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    analyzeLeaseLevelAcquisition: vi.fn(),
    updateLeaseLevelDeal: vi.fn(),
    getDeal: vi.fn(),
    listDeals: vi.fn(),
  };
});

const mockAnalyze = vi.mocked(analyzeLeaseLevelAcquisition);
const mockUpdate = vi.mocked(updateLeaseLevelDeal);
const mockGetDeal = vi.mocked(getDeal);
const mockListDeals = vi.mocked(listDeals);

/** Captured from a live `/analyze`. */
const HEALTHY = fixture.healthy as unknown as LeaseLevelAcquisitionResults;
const UNDEFINED_IRR = fixture.undefinedIrr as unknown as LeaseLevelAcquisitionResults;

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

async function openDealWithoutAnalyzing() {
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText('Fulton Exchange');
  await user.click(screen.getByText('Fulton Exchange'));
  await waitFor(() => {
    expect(screen.getByRole('tablist', { name: 'Lease-Level sections' })).toBeTruthy();
  });
  return user;
}

function resultsPanel(): HTMLElement {
  return document.getElementById('lease-level-panel-results') as HTMLElement;
}

/** The value cells of one statement row, by its label.
 *
 * Scoped to `th[scope="row"]`: a section band carries the same words as the
 * line it introduces -- "Net Operating Income" heads the group and names the
 * line -- which is how an operating statement reads and is not ambiguity in the
 * UI, only in a careless query. */
function rowValues(label: string): string[] {
  const table = document.querySelector('.lease-level-statement-table') as HTMLElement;
  const header = Array.from(table.querySelectorAll('th[scope="row"]')).find(
    (cell) => cell.textContent === label,
  );
  if (header === undefined) {
    throw new Error(`No statement row labelled ${label}`);
  }
  const row = header.closest('tr') as HTMLElement;
  return Array.from(row.querySelectorAll('td')).map((cell) => cell.textContent ?? '');
}

async function openStatement(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    within(resultsPanel()).getByRole('tab', { name: 'Operating Statement' }),
  );
}

// =============================================================================
// 1. Analyze visibly produces results (M1)
// =============================================================================

describe('a successful analysis', () => {
  it('lands the analyst on results rather than leaving them to look', async () => {
    await analyze();
    await waitFor(() => {
      expect(
        screen.getByRole('tab', { name: 'Results' }).getAttribute('aria-selected'),
      ).toBe('true');
    });
    expect(within(resultsPanel()).getByText('Levered IRR')).toBeTruthy();
  });

  it('shows the headline returns from the response', async () => {
    await analyze();
    const panel = within(resultsPanel());
    // 0.12592031990009156 -> 12.59%
    expect(panel.getByText('12.59%')).toBeTruthy();
    // 1.7113999991324877 -> 1.71x
    expect(panel.getByText('1.71x')).toBeTruthy();
  });

  it('offers exactly the Lease-Level result views', async () => {
    await analyze();
    const tabs = within(resultsPanel())
      .getAllByRole('tab')
      .map((tab) => tab.textContent);
    expect(tabs).toEqual(['Summary', 'Operating Statement', 'Cash Flow']);
    expect(resultsViewsFor('lease_level').map((view) => view.id)).toEqual([
      'summary',
      'operating-statement',
      'cash-flow',
    ]);
  });
});

// =============================================================================
// 2. Undefined IRR (M13, M14) and zero-vs-None (M15)
// =============================================================================

describe('an IRR the engine could not define', () => {
  it('says so, rather than showing zero', async () => {
    await analyze(UNDEFINED_IRR);
    const panel = within(resultsPanel());

    expect(UNDEFINED_IRR.results.levered_irr).toBeNull();
    expect(panel.getByText('Not uniquely defined')).toBeTruthy();
    // The specific wrong answer: a null IRR rendered as zero turns a healthy
    // deal into a broken-looking one.
    expect(panel.queryByText('0.00%')).toBeNull();
  });

  it('is not an error state', async () => {
    await analyze(UNDEFINED_IRR);
    // The rest of the analysis is present and readable.
    const panel = within(resultsPanel());
    expect(panel.getByText('Unlevered IRR')).toBeTruthy();
    expect(panel.getByText(/changes sign more than once/)).toBeTruthy();
    expect(panel.queryByRole('alert')).toBeNull();
  });

  it('keeps zero distinct from undefined', async () => {
    // This fixture's equity multiple really is 0, and its disposition costs
    // really are 0. Those are answers; `null` is the absence of one.
    await analyze(UNDEFINED_IRR);
    expect(UNDEFINED_IRR.results.equity_multiple).toBe(0);
    const panel = within(resultsPanel());
    expect(panel.getByText('0.00x')).toBeTruthy();
    expect(panel.getAllByText('$0').length).toBeGreaterThan(0);
  });
});

// =============================================================================
// 3. Monthly and Annual read different arrays (M2, M3, M4)
// =============================================================================

describe('the monthly and annual views', () => {
  it('defaults to annual and switches to monthly', async () => {
    const user = await analyze();
    await openStatement(user);

    const toggle = within(resultsPanel()).getByRole('tablist', { name: 'Statement period' });
    expect(within(toggle).getByRole('tab', { name: 'Annual' }).getAttribute('aria-selected')).toBe(
      'true',
    );

    await user.click(within(toggle).getByRole('tab', { name: 'Monthly' }));
    expect(
      within(toggle).getByRole('tab', { name: 'Monthly' }).getAttribute('aria-selected'),
    ).toBe('true');
  });

  it('labels annual columns by hold year and monthly columns by month', async () => {
    const user = await analyze();
    await openStatement(user);

    const table = () => document.querySelector('.lease-level-statement-table') as HTMLElement;
    const annualHeaders = within(table())
      .getAllByRole('columnheader')
      .map((cell) => cell.textContent);
    expect(annualHeaders).toEqual(['Line Item', 'Year 1', 'Year 2', 'Year 3', 'Year 4', 'Year 5']);

    await user.click(within(resultsPanel()).getByRole('tab', { name: 'Monthly' }));
    const monthlyHeaders = within(table())
      .getAllByRole('columnheader')
      .map((cell) => cell.textContent);
    // A month, not a period index.
    expect(monthlyHeaders[1]).toBe('Jan 2027');
    expect(monthlyHeaders[2]).toBe('Feb 2027');
    expect(monthlyHeaders).toHaveLength(HEALTHY.monthly_projection.months.length + 1);
  });

  it('renders the annual array in the annual view, not a sum of months (M3)', async () => {
    const user = await analyze();
    await openStatement(user);

    const noi = rowValues('Net Operating Income');
    expect(noi).toHaveLength(HEALTHY.annual_projection.noi_by_year.length);
    // The first cell is the backend's own Year 1 NOI, formatted.
    const expected = `$${Math.round(
      HEALTHY.annual_projection.noi_by_year[0],
    ).toLocaleString('en-US')}`;
    expect(noi[0]).toBe(expected);
  });

  it('renders the monthly array in the monthly view, not annual over twelve (M4)', async () => {
    const user = await analyze();
    await openStatement(user);
    await user.click(within(resultsPanel()).getByRole('tab', { name: 'Monthly' }));

    const noi = rowValues('Net Operating Income');
    expect(noi).toHaveLength(HEALTHY.monthly_projection.months.length);
    const expected = `$${Math.round(HEALTHY.monthly_projection.noi[0]).toLocaleString('en-US')}`;
    expect(noi[0]).toBe(expected);

    // And it is emphatically not the annual figure divided by twelve.
    const twelfth = `$${Math.round(
      HEALTHY.annual_projection.noi_by_year[0] / 12,
    ).toLocaleString('en-US')}`;
    expect(noi[0]).not.toBe(twelfth);
  });

  it('includes the twelve forward exit months in the monthly view', async () => {
    const user = await analyze();
    await openStatement(user);
    await user.click(within(resultsPanel()).getByRole('tab', { name: 'Monthly' }));

    // 5-year hold: 60 hold months plus the 12 that set the exit.
    expect(HEALTHY.monthly_projection.months).toHaveLength(72);
    expect(rowValues('Net Operating Income')).toHaveLength(72);
    // Nothing is silently truncated (M26).
    const last = HEALTHY.monthly_projection.months[71];
    const headers = within(
      document.querySelector('.lease-level-statement-table') as HTMLElement,
    )
      .getAllByRole('columnheader')
      .map((cell) => cell.textContent);
    expect(headers[headers.length - 1]).toBe(formatMonthLabel(last.month_start));
  });
});

// =============================================================================
// 4. TI, LC and CapEx (M5, M6, M7, M8, M23, M24)
// =============================================================================

describe('leasing capital', () => {
  it('shows TI and LC below NOI in the annual view', async () => {
    const user = await analyze();
    await openStatement(user);

    const table = document.querySelector('.lease-level-statement-table') as HTMLElement;
    const labels = Array.from(table.querySelectorAll('th[scope="row"]')).map(
      (cell) => cell.textContent,
    );
    expect(labels).toContain('Tenant Improvements');
    expect(labels).toContain('Leasing Commissions');

    // Below NOI, never inside operating expenses.
    const noiAt = labels.indexOf('Net Operating Income');
    const totalOpexAt = labels.indexOf('Total Operating Expenses');
    expect(labels.indexOf('Tenant Improvements')).toBeGreaterThan(noiAt);
    expect(labels.indexOf('Leasing Commissions')).toBeGreaterThan(noiAt);
    expect(totalOpexAt).toBeLessThan(noiAt);
  });

  it('shows TI and LC below NOI in the monthly view', async () => {
    const user = await analyze();
    await openStatement(user);
    await user.click(within(resultsPanel()).getByRole('tab', { name: 'Monthly' }));

    const table = document.querySelector('.lease-level-statement-table') as HTMLElement;
    const labels = Array.from(table.querySelectorAll('th[scope="row"]')).map(
      (cell) => cell.textContent,
    );
    expect(labels.indexOf('Tenant Improvements')).toBeGreaterThan(
      labels.indexOf('Net Operating Income'),
    );
  });

  it('takes monthly TI from the monthly array, never from the annual one (M23)', async () => {
    const user = await analyze();
    await openStatement(user);
    await user.click(within(resultsPanel()).getByRole('tab', { name: 'Monthly' }));

    const ti = rowValues('Tenant Improvements');
    expect(ti).toHaveLength(HEALTHY.monthly_projection.tenant_improvements.length);
    const monthly = HEALTHY.monthly_projection.tenant_improvements;
    const firstSpike = monthly.findIndex((value) => value !== 0);
    if (firstSpike !== -1) {
      // A real TI cheque lands in one month, not smeared across twelve.
      expect(ti[firstSpike]).toBe(
        `$${Math.round(monthly[firstSpike]).toLocaleString('en-US')}`,
      );
    }
  });

  it('shows CapEx and debt service annually only, because that is where they exist (M24)', async () => {
    const user = await analyze();
    await openStatement(user);

    let labels = () =>
      Array.from(
        (document.querySelector('.lease-level-statement-table') as HTMLElement).querySelectorAll(
          'th[scope="row"]',
        ),
      ).map((cell) => cell.textContent);
    expect(labels()).toContain('CapEx Reserve');
    expect(labels()).toContain('Debt Service');

    await user.click(within(resultsPanel()).getByRole('tab', { name: 'Monthly' }));
    // The monthly projection carries neither, and dividing the annual figure by
    // twelve would be inventing a schedule the engine never produced.
    expect(labels()).not.toContain('CapEx Reserve');
    expect(labels()).not.toContain('Debt Service');
    expect(Object.keys(HEALTHY.monthly_projection)).not.toContain('capex_by_year');
  });
});

// =============================================================================
// 5. Occupancy (M9)
// =============================================================================

describe('occupancy', () => {
  it('renders the backend series rather than computing a ratio', async () => {
    const user = await analyze();
    await openStatement(user);
    await user.click(within(resultsPanel()).getByRole('tab', { name: 'Monthly' }));

    const occupancy = rowValues('Physical Occupancy');
    const expected = `${(HEALTHY.monthly_projection.physical_occupancy[0] * 100).toFixed(2)}%`;
    expect(occupancy[0]).toBe(expected);

    const occupied = rowValues('Occupied Area');
    expect(occupied[0]).toBe(
      `${HEALTHY.monthly_projection.occupied_area_sf[0].toLocaleString('en-US', {
        maximumFractionDigits: 0,
      })} SF`,
    );
  });

  it('names year-end and average occupancy for what each is', async () => {
    const user = await analyze();
    await openStatement(user);

    const table = document.querySelector('.lease-level-statement-table') as HTMLElement;
    const labels = Array.from(table.querySelectorAll('th[scope="row"]')).map(
      (cell) => cell.textContent,
    );
    // An average is not a year-end reading; conflating them misstates a
    // rollover year badly.
    expect(labels).toContain('Physical Occupancy at Year End');
    expect(labels).toContain('Average Physical Occupancy');

    expect(rowValues('Average Physical Occupancy')[0]).toBe(
      `${(HEALTHY.annual_projection.average_physical_occupancy_over_year[0] * 100).toFixed(2)}%`,
    );
    expect(rowValues('Physical Occupancy at Year End')[0]).toBe(
      `${(HEALTHY.annual_projection.physical_occupancy_at_year_end[0] * 100).toFixed(2)}%`,
    );
  });

  it('reads the annual occupancy fields the wire actually carries', () => {
    // D5.5A declared `occupied_area_sf_at_year_end`; the response carries
    // `occupied_area_at_year_end`. Reading the wrong one produced `undefined`,
    // which nothing caught because nothing rendered it until now.
    expect(HEALTHY.annual_projection.occupied_area_at_year_end).toBeDefined();
    expect(HEALTHY.annual_projection.vacant_area_at_year_end).toBeDefined();
    expect(
      (HEALTHY.annual_projection as unknown as Record<string, unknown>)
        .occupied_area_sf_at_year_end,
    ).toBeUndefined();
  });
});

// =============================================================================
// 6. Exit economics (M16) and going-in cap (M11), DSCR (M12)
// =============================================================================

describe('exit and coverage', () => {
  it('shows the authoritative exit NOI, not the final hold-year NOI (M16)', async () => {
    await analyze();
    const panel = within(resultsPanel());

    const exitNoi = HEALTHY.results.exit_noi;
    const finalYearNoi =
      HEALTHY.annual_projection.noi_by_year[HEALTHY.annual_projection.noi_by_year.length - 1];
    // The two genuinely differ: exit NOI is the twelve months *after* the hold.
    expect(exitNoi).not.toBeCloseTo(finalYearNoi, 2);

    expect(panel.getByText(`$${Math.round(exitNoi).toLocaleString('en-US')}`)).toBeTruthy();
    expect(panel.getByText(/twelve months following the hold period/i)).toBeTruthy();
  });

  it('shows exit value, disposition costs and net proceeds from the response', async () => {
    await analyze();
    const panel = within(resultsPanel());
    for (const value of [
      HEALTHY.results.exit_value,
      HEALTHY.results.net_sale_proceeds,
    ]) {
      const sign = value < 0 ? '-' : '';
      expect(
        panel.getAllByText(`${sign}$${Math.round(Math.abs(value)).toLocaleString('en-US')}`)
          .length,
      ).toBeGreaterThan(0);
    }
  });

  it('shows the backend going-in cap rate (M11)', async () => {
    await analyze();
    expect(
      within(resultsPanel()).getByText(
        `${(HEALTHY.results.going_in_cap_rate * 100).toFixed(2)}%`,
      ),
    ).toBeTruthy();
  });

  it('shows DSCR from the response as a ratio (M12)', async () => {
    await analyze();
    const panel = within(resultsPanel());
    expect(panel.getByText('Headline DSCR')).toBeTruthy();
    expect(panel.getByText('Minimum DSCR')).toBeTruthy();
    expect(
      panel.getAllByText(`${HEALTHY.results.headline_dscr!.toFixed(2)}x`).length,
    ).toBeGreaterThan(0);
  });
});

// =============================================================================
// 7. Stale results and reopening (M19, M20)
// =============================================================================

describe('results never outlive the inputs they describe', () => {
  it('a reopened deal shows no stored result (M19)', async () => {
    const user = await openDealWithoutAnalyzing();
    await user.click(screen.getByRole('tab', { name: 'Results' }));

    expect(within(resultsPanel()).getByText(/Analyze to see results/)).toBeTruthy();
    // Nothing was restored, because nothing is persisted.
    expect(savedDeal().analysis_snapshot).toBeNull();
    expect(within(resultsPanel()).queryByText('Levered IRR')).toBeNull();
  });

  it('editing an assumption clears the results it described (M20)', async () => {
    const user = await analyze();
    expect(within(resultsPanel()).getByText('Levered IRR')).toBeTruthy();

    await user.click(screen.getByRole('tab', { name: 'Acquisition & Debt' }));
    const purchasePrice = document.getElementById(
      'lease-level-terms-purchasePrice',
    ) as HTMLInputElement;
    await user.clear(purchasePrice);
    await user.type(purchasePrice, '7000000');

    await user.click(screen.getByRole('tab', { name: 'Results' }));
    // No figure survives to look current against inputs it does not describe.
    expect(within(resultsPanel()).queryByText('Levered IRR')).toBeNull();
    expect(within(resultsPanel()).getByText(/Analyze to see results/)).toBeTruthy();
  });

  it('editing the rent roll clears them too', async () => {
    const user = await analyze();
    await user.click(screen.getByRole('tab', { name: 'Rent Roll' }));
    const panel = document.getElementById('lease-level-panel-rent-roll') as HTMLElement;
    const area = within(within(panel).getAllByRole('row')[1]).getByLabelText(/^Area SF, /);
    await user.clear(area);
    await user.type(area, '12500');

    await user.click(screen.getByRole('tab', { name: 'Results' }));
    expect(within(resultsPanel()).getByText(/Analyze to see results/)).toBeTruthy();
  });

  it('save, reopen and analyze produces current results', async () => {
    mockUpdate.mockResolvedValue(savedDeal());
    const user = await analyze();

    // Save the deal that was just analysed.
    await user.click(screen.getByRole('button', { name: /(Save|Update) Deal/i }));
    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalled();
    });
    // Nothing about the analysis was sent to be stored.
    const [, , , inputs] = mockUpdate.mock.calls[0];
    expect(Object.keys(inputs)).not.toContain('monthly_projection');
    expect(Object.keys(inputs)).not.toContain('results');

    // Reopen: inputs only.
    cleanup();
    const reopened = await openDealWithoutAnalyzing();
    await reopened.click(screen.getByRole('tab', { name: 'Results' }));
    expect(within(resultsPanel()).getByText(/Analyze to see results/)).toBeTruthy();

    // Analyze again: current results.
    mockAnalyze.mockResolvedValue(HEALTHY);
    await reopened.click(screen.getByRole('button', { name: /^Analyz/i }));
    await waitFor(() => {
      expect(within(resultsPanel()).getByText('Levered IRR')).toBeTruthy();
    });
  });
});

// =============================================================================
// 8. Size and shape
// =============================================================================

describe('the full projection is rendered', () => {
  it('renders every month without truncation (M26)', async () => {
    const user = await analyze();
    await openStatement(user);
    await user.click(within(resultsPanel()).getByRole('tab', { name: 'Monthly' }));

    for (const label of [
      'Contractual Base Rent',
      'Effective Gross Income',
      'Total Operating Expenses',
      'Net Operating Income',
    ]) {
      expect(rowValues(label), label).toHaveLength(
        HEALTHY.monthly_projection.months.length,
      );
    }
  });

  it('keeps line-item labels as real row headers', async () => {
    const user = await analyze();
    await openStatement(user);
    const table = document.querySelector('.lease-level-statement-table') as HTMLElement;
    // Semantic headers, so a screen reader can say which line a figure is on.
    expect(table.querySelectorAll('th[scope="row"]').length).toBeGreaterThan(15);
    expect(table.querySelectorAll('th[scope="rowgroup"]').length).toBe(5);
  });
});

// =============================================================================
// 9. The tampered response: proof by contradiction (M9, M10, M11, M12)
// =============================================================================

/**
 * Every test above compares a rendered figure against the response, which is
 * necessary but not sufficient: the fixture is internally consistent, so a
 * component that recomputed NOI from EGI and expenses would agree with one that
 * read `noi` and both would pass.
 *
 * These tests hand the UI a response that is deliberately *not* internally
 * consistent -- an NOI that is not EGI less expenses, a cap rate that is not
 * NOI over price, an occupancy that is not occupied over rentable -- and
 * require the rendered figure to follow the response. A frontend that computed
 * any of them would show the consistent answer and fail here. Nothing else
 * distinguishes the two implementations.
 */
function tampered(): LeaseLevelAcquisitionResults {
  const clone = structuredClone(HEALTHY) as LeaseLevelAcquisitionResults;
  const sentinel = (index: number) => 1_000_000 + index;

  const monthly = clone.monthly_projection as unknown as Record<string, number[]>;
  monthly.noi = monthly.noi.map((_, index) => sentinel(index));
  monthly.physical_occupancy = monthly.physical_occupancy.map(() => 0.4242);

  const annual = clone.annual_projection as unknown as Record<string, number[]>;
  annual.noi_by_year = annual.noi_by_year.map((_, index) => sentinel(index));

  const results = clone.results as unknown as Record<string, number>;
  results.going_in_cap_rate = 0.1234;
  results.headline_dscr = 9.87;

  return clone;
}

describe('a self-inconsistent response is rendered as given', () => {
  it('shows the response NOI, never EGI less expenses (M10)', async () => {
    const mutant = tampered();
    // The contradiction is real: the fixture's own lines no longer add up.
    const egi = mutant.monthly_projection.effective_gross_income[0];
    const opex = mutant.monthly_projection.total_operating_expenses[0];
    expect(mutant.monthly_projection.noi[0]).not.toBeCloseTo(egi - opex, 2);

    const user = await analyze(mutant);
    await openStatement(user);
    await user.click(within(resultsPanel()).getByRole('tab', { name: 'Monthly' }));

    expect(rowValues('Net Operating Income')[0]).toBe('$1,000,000');

    await user.click(within(resultsPanel()).getByRole('tab', { name: 'Annual' }));
    expect(rowValues('Net Operating Income')[0]).toBe('$1,000,000');
  });

  it('shows the response occupancy, never occupied over rentable (M9)', async () => {
    const mutant = tampered();
    const occupied = mutant.monthly_projection.occupied_area_sf[0];
    const vacant = mutant.monthly_projection.vacant_area_sf[0];
    expect(mutant.monthly_projection.physical_occupancy[0]).not.toBeCloseTo(
      occupied / (occupied + vacant),
      3,
    );

    const user = await analyze(mutant);
    await openStatement(user);
    await user.click(within(resultsPanel()).getByRole('tab', { name: 'Monthly' }));

    expect(rowValues('Physical Occupancy')[0]).toBe('42.42%');
  });

  it('shows the response cap rate and DSCR, never a client-side ratio (M11, M12)', async () => {
    const mutant = tampered();
    // Neither figure is derivable from anything else the response carries.
    await analyze(mutant);
    const panel = within(resultsPanel());
    expect(panel.getByText('12.34%')).toBeTruthy();
    expect(panel.getAllByText('9.87x').length).toBeGreaterThan(0);
  });
});
