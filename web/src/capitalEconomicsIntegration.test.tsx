/**
 * Phase 6 Gate D6.7 -- Capital Economics in the real application, in all three
 * modes.
 *
 * **Nothing in `api.ts` is mocked.** The real `App` and client functions run, and
 * `fetch` is replaced by a small backend that holds deals in a map and answers
 * `/analyze` with the captured responses in `capitalEconomicsFixture.json` --
 * the same pattern `businessPlanPersistence.test.tsx` uses. So these tests
 * exercise the wiring the unit tests cannot: that each mode hands the section its
 * own authoritative result, and the Purchase Price of the request that produced
 * it; that the view sits inside Underwrite -> Results; and that a Business Plan
 * edit takes the section away with the rest of the result.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import { clone } from './leaseLevelDealFixture';
import { formatCurrency } from './format';
import fixture from './capitalEconomicsFixture.json';
import type { BusinessPlanInput } from './businessPlan';
import type {
  AcquisitionRequest,
  AcquisitionResults,
  AcquisitionTermsRequest,
  Deal,
  DetailedAcquisitionResults,
  DetailedOperatingInputsRequest,
} from './types';
import type {
  LeaseLevelAcquisitionResults,
  LeaseLevelOperatingInputsRequest,
  LeaseLevelPropertyInputsRequest,
  LeaseRequest,
  MarketLeasingAssumptionsRequest,
  SuiteRequest,
} from './leaseLevelTypes';

// =============================================================================
// Captured cases
// =============================================================================

const QUICK = fixture.quick.v5_mixed;
const DETAILED = fixture.detailed.v5_mixed;
const LEASE_LEVEL = fixture.lease_level.v9_leasing_and_project_capital;

const QUICK_RESULTS = QUICK.response as unknown as AcquisitionResults;
const DETAILED_ANALYSIS = DETAILED.response as unknown as DetailedAcquisitionResults;
const LEASE_LEVEL_ANALYSIS = LEASE_LEVEL.response as unknown as LeaseLevelAcquisitionResults;

const TIMESTAMPS = {
  created_at: '2026-09-12T09:00:00+00:00',
  updated_at: '2026-09-12T09:00:00+00:00',
};

const NO_SNAPSHOTS = {
  ai_snapshot: null,
  one_way_sensitivity_snapshot: null,
  two_way_sensitivity_snapshot: null,
};

const NO_LEASE_LEVEL_INPUTS = {
  property_inputs: null,
  operating_inputs: null,
  market_leasing: null,
  suites: null,
  leases: null,
};

/** A Quick `/analyze` body is the flat inputs object; the deal stores it without
 * the two keys the endpoint sets aside. */
function quickInputs(): AcquisitionRequest {
  return Object.fromEntries(
    Object.entries(QUICK.request).filter(
      ([key]) => key !== 'operating_mode' && key !== 'business_plan',
    ),
  ) as unknown as AcquisitionRequest;
}

function quickDeal(snapshot: AcquisitionResults | null = QUICK_RESULTS): Deal {
  return {
    id: 'quick-ce',
    name: 'Harbor Point',
    operating_mode: 'quick',
    inputs: quickInputs(),
    terms: null,
    detailed_operating_inputs: null,
    ...NO_LEASE_LEVEL_INPUTS,
    business_plan: QUICK.request.business_plan as unknown as BusinessPlanInput,
    asset_type: null,
    asset_subtype: null,
    deal_context: null,
    analysis_snapshot: snapshot,
    ...NO_SNAPSHOTS,
    ...TIMESTAMPS,
  };
}

function detailedDeal(snapshot: DetailedAcquisitionResults = DETAILED_ANALYSIS): Deal {
  return {
    id: 'detailed-ce',
    name: 'Canal Works',
    operating_mode: 'detailed',
    inputs: null,
    terms: DETAILED.request.terms as unknown as AcquisitionTermsRequest,
    detailed_operating_inputs: DETAILED.request
      .detailed_operating_inputs as unknown as DetailedOperatingInputsRequest,
    ...NO_LEASE_LEVEL_INPUTS,
    business_plan: DETAILED.request.business_plan as unknown as BusinessPlanInput,
    asset_type: null,
    asset_subtype: null,
    deal_context: null,
    analysis_snapshot: snapshot,
    ...NO_SNAPSHOTS,
    ...TIMESTAMPS,
  };
}

function leaseLevelDeal(purchasePrice = LEASE_LEVEL.request.terms.purchase_price): Deal {
  const request = LEASE_LEVEL.request;
  return {
    id: 'lease-ce',
    name: 'Fulton Exchange',
    operating_mode: 'lease_level',
    inputs: null,
    terms: { ...(request.terms as unknown as AcquisitionTermsRequest), purchase_price: purchasePrice },
    detailed_operating_inputs: null,
    property_inputs: request.property_inputs as unknown as LeaseLevelPropertyInputsRequest,
    operating_inputs: request.operating_inputs as unknown as LeaseLevelOperatingInputsRequest,
    market_leasing: request.market_leasing as unknown as MarketLeasingAssumptionsRequest,
    suites: request.suites as unknown as SuiteRequest[],
    leases: request.leases as unknown as LeaseRequest[],
    business_plan: request.business_plan as unknown as BusinessPlanInput,
    asset_type: null,
    asset_subtype: null,
    deal_context: null,
    // Lease-Level persists no analysis snapshot (D5 decision D5).
    analysis_snapshot: null,
    ...NO_SNAPSHOTS,
    ...TIMESTAMPS,
  };
}

// =============================================================================
// The backend
// =============================================================================

const store = new Map<string, Deal>();
let leaseLevelAnswer: LeaseLevelAcquisitionResults = LEASE_LEVEL_ANALYSIS;
let analyzeCalls = 0;

function reply(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => clone(body),
  } as Response;
}

async function backend(url: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const path = String(url).replace('http://127.0.0.1:8000', '');
  const method = init?.method ?? 'GET';
  const body =
    typeof init?.body === 'string' ? (JSON.parse(init.body) as Record<string, unknown>) : undefined;

  if (method === 'GET' && path === '/deals') {
    return reply(200, [...store.values()]);
  }
  if (path === '/deals/fingerprint') {
    return reply(200, { financial_input_fingerprint: 'fp', ai_context_fingerprint: 'fp-ai' });
  }
  const deal = /^\/deals\/([^/]+)$/.exec(path);
  if (method === 'GET' && deal !== null) {
    const existing = store.get(decodeURIComponent(deal[1]));
    return existing === undefined ? reply(404, { detail: 'not found' }) : reply(200, existing);
  }
  if (path === '/analyze' && body?.operating_mode === 'lease_level') {
    analyzeCalls += 1;
    return reply(200, leaseLevelAnswer);
  }
  // Presets, break-even and anything else: refused, so no panel needs a fixture.
  return reply(500, {});
}

beforeEach(() => {
  store.clear();
  leaseLevelAnswer = LEASE_LEVEL_ANALYSIS;
  analyzeCalls = 0;
  for (const deal of [quickDeal(), detailedDeal(), leaseLevelDeal()]) {
    store.set(deal.id, clone(deal));
  }
  vi.stubGlobal('fetch', vi.fn(backend));
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// =============================================================================
// Driving the app
// =============================================================================

type User = ReturnType<typeof userEvent.setup>;

async function launchAndOpen(name: string): Promise<User> {
  const user = userEvent.setup({ delay: null });
  render(<App />);
  const list = await waitFor(() => {
    const node = document.querySelector('.sidebar-deal-list');
    expect(node).not.toBeNull();
    return node as HTMLElement;
  });
  await user.click(await within(list).findByText(name));
  await waitFor(() => expect(screen.getByDisplayValue(name)).toBeTruthy());
  return user;
}

function tablist(label: string): HTMLElement {
  return document.querySelector(`[aria-label="${label}"]`) as HTMLElement;
}

/** Quick and Detailed: Underwrite -> Results -> Capital Economics. */
async function openQuickOrDetailedCapitalEconomics(user: User): Promise<HTMLElement> {
  await user.click(screen.getByRole('tab', { name: 'Underwrite' }));
  await user.click(within(tablist('Underwrite sections')).getByRole('tab', { name: 'Results' }));
  await user.click(
    within(tablist('Results views')).getByRole('tab', { name: 'Capital Economics' }),
  );
  const panel = document.getElementById('underwrite-results-panel-capital-economics');
  expect(panel).not.toBeNull();
  expect(panel!.hasAttribute('hidden')).toBe(false);
  return panel!;
}

/** Lease-Level: Analyze, which lands on Results, then Capital Economics. */
async function analyzeLeaseLevelCapitalEconomics(user: User): Promise<HTMLElement> {
  await waitFor(() =>
    expect(screen.getByRole('tablist', { name: 'Lease-Level sections' })).toBeTruthy(),
  );
  await user.click(screen.getByRole('button', { name: /^Analyz/i }));
  await waitFor(() => expect(analyzeCalls).toBe(1));
  const results = await waitFor(() => {
    const node = document.getElementById('lease-level-panel-results');
    expect(node).not.toBeNull();
    expect(within(node as HTMLElement).queryByRole('tab', { name: 'Capital Economics' })).toBeTruthy();
    return node as HTMLElement;
  });
  await user.click(within(results).getByRole('tab', { name: 'Capital Economics' }));
  return within(results).getByRole('region', { name: 'Capital Economics' });
}

function ledger(scope: HTMLElement, name: string): Record<string, string> {
  const table = within(within(scope).getByRole('region', { name })).getByRole('table');
  const values: Record<string, string> = {};
  for (const row of Array.from(table.querySelectorAll('tr'))) {
    const header = row.querySelector('th[scope="row"]');
    const cell = row.querySelector('td');
    if (header !== null && cell !== null) {
      values[header.textContent ?? ''] = cell.textContent ?? '';
    }
  }
  return values;
}

function scheduleRows(scope: HTMLElement): string[][] {
  const table = within(within(scope).getByRole('region', { name: 'Capital Schedule' })).getByRole(
    'table',
  );
  return Array.from(table.querySelectorAll('tbody tr')).map((row) =>
    Array.from(row.children).map((cell) => cell.textContent ?? ''),
  );
}

// =============================================================================
// 1. Each mode's integration
// =============================================================================

describe('Quick', () => {
  it('reports Capital Economics under Underwrite -> Results from its restored analysis', async () => {
    const user = await launchAndOpen('Harbor Point');
    const panel = await openQuickOrDetailedCapitalEconomics(user);

    const uses = ledger(panel, 'Sources & Uses at Closing');
    // Purchase Price is the analyzed request's input; everything else is a field.
    expect(uses['Purchase Price']).toBe(formatCurrency(QUICK.request.purchase_price));
    expect(uses['Total Closing Uses']).toBe(formatCurrency(QUICK_RESULTS.total_closing_uses));
    expect(uses['Total Closing Sources']).toBe(formatCurrency(QUICK_RESULTS.total_closing_sources));
    expect(ledger(panel, 'Project Returns')['Total Profit']).toBe(
      formatCurrency(QUICK_RESULTS.total_profit),
    );
    expect(scheduleRows(panel)[0]).toContain('$250,000');
    expect(
      within(panel).getByRole('note', { name: 'Post-Hold Project Capital' }).textContent,
    ).toContain('$500,000 is modeled after the current hold and is excluded from seller returns.');

    // The Live Case rail is left alone: none of the D6 reporting moved into it.
    const rail = document.querySelector('.live-case') as HTMLElement;
    for (const label of ['Total Equity Invested', 'Total Cash Returned', 'Total Profit', 'Capital Schedule']) {
      expect(rail.textContent, label).not.toContain(label);
    }
  });

  it('shows no figures before an analysis exists (unanalyzed)', async () => {
    store.set('quick-ce', clone(quickDeal(null)));
    const user = await launchAndOpen('Harbor Point');
    await user.click(screen.getByRole('tab', { name: 'Underwrite' }));
    await user.click(within(tablist('Underwrite sections')).getByRole('tab', { name: 'Results' }));
    expect(screen.getByText('Analyze the deal to view results.')).toBeTruthy();
    expect(document.querySelector('.capital-economics')).toBeNull();
    expect(screen.queryByRole('tab', { name: 'Capital Economics' })).toBeNull();
  });

  it('takes Capital Economics away with the rest of the result when the Business Plan is edited', async () => {
    const user = await launchAndOpen('Harbor Point');
    await openQuickOrDetailedCapitalEconomics(user);
    expect(document.querySelector('.capital-economics')).not.toBeNull();

    await user.click(
      within(tablist('Underwrite sections')).getByRole('tab', { name: 'Acquisition' }),
    );
    await user.click(screen.getByRole('button', { name: 'Add Project Capital' }));
    await user.click(within(tablist('Underwrite sections')).getByRole('tab', { name: 'Results' }));

    expect(screen.getByText('Analyze the deal to view results.')).toBeTruthy();
    expect(document.querySelector('.capital-economics')).toBeNull();
    expect(screen.queryByText(formatCurrency(QUICK_RESULTS.total_closing_uses))).toBeNull();
  });
});

describe('Detailed', () => {
  it('reports Capital Economics from the envelope’s results, with its own Purchase Price', async () => {
    const user = await launchAndOpen('Canal Works');
    const panel = await openQuickOrDetailedCapitalEconomics(user);
    const results = DETAILED_ANALYSIS.results;
    const uses = ledger(panel, 'Sources & Uses at Closing');
    expect(uses['Purchase Price']).toBe(formatCurrency(DETAILED.request.terms.purchase_price));
    expect(uses['Total Closing Uses']).toBe(formatCurrency(results.total_closing_uses));
    const returns = ledger(panel, 'Project Returns');
    expect(returns['Total Equity Invested']).toBe(formatCurrency(results.total_equity_invested));
    expect(returns['Total Profit']).toBe(formatCurrency(results.total_profit));
    // Detailed models no TI / LC, so the schedule has no such columns.
    const header = within(panel).getByRole('region', { name: 'Capital Schedule' }).textContent!;
    expect(header).not.toContain('Tenant Improvements');
  });

  it('takes Capital Economics away when the Business Plan is edited', async () => {
    const user = await launchAndOpen('Canal Works');
    await openQuickOrDetailedCapitalEconomics(user);
    await user.click(
      within(tablist('Underwrite sections')).getByRole('tab', { name: 'Acquisition' }),
    );
    await user.click(screen.getByRole('button', { name: 'Add Owner Expense' }));
    await user.click(within(tablist('Underwrite sections')).getByRole('tab', { name: 'Results' }));
    expect(screen.getByText('Analyze the deal to view results.')).toBeTruthy();
    expect(document.querySelector('.capital-economics')).toBeNull();
  });
});

describe('Lease-Level', () => {
  it('reports TI, LC and Project Capital separately, with the analyzed Purchase Price', async () => {
    const user = await launchAndOpen('Fulton Exchange');
    const panel = await analyzeLeaseLevelCapitalEconomics(user);
    const results = LEASE_LEVEL_ANALYSIS.results;

    expect(ledger(panel, 'Sources & Uses at Closing')['Purchase Price']).toBe('$9,000,000');
    const yearFive = scheduleRows(panel)[5];
    expect(yearFive).toEqual([
      'Year 5',
      formatCurrency(results.capex_by_year[4]),
      formatCurrency(results.tenant_improvements_by_year[4]),
      formatCurrency(results.leasing_commissions_by_year[4]),
      formatCurrency(results.project_capital_by_year[4]),
      formatCurrency(results.owner_expenses_by_year[4]),
    ]);
    expect(ledger(panel, 'Project Returns')['Levered IRR']).toBe('N/A');
    expect(
      within(panel).getByText(
        'Levered IRR is not reported because the modeled cash-flow pattern changes sign more than once.',
      ),
    ).toBeTruthy();
  });

  it('shows no figures before Analyze, since Lease-Level stores no result', async () => {
    await launchAndOpen('Fulton Exchange');
    await waitFor(() =>
      expect(screen.getByRole('tablist', { name: 'Lease-Level sections' })).toBeTruthy(),
    );
    expect(document.querySelector('.capital-economics')).toBeNull();
  });

  it('takes Capital Economics away when the Business Plan is edited', async () => {
    const user = await launchAndOpen('Fulton Exchange');
    await analyzeLeaseLevelCapitalEconomics(user);
    expect(document.querySelector('.capital-economics')).not.toBeNull();

    await user.click(
      within(screen.getByRole('tablist', { name: 'Lease-Level sections' })).getByRole('tab', {
        name: 'Acquisition & Debt',
      }),
    );
    await user.click(screen.getByRole('button', { name: 'Add Project Capital' }));
    expect(document.querySelector('.capital-economics')).toBeNull();
  });
});

// =============================================================================
// 2. The cross-mode oracle (Part AI)
//
// The SAME deterministic result, delivered through each mode's own path, must
// read identically: the same Sources & Uses, Project Returns and Owner Cash Flow,
// and a capital schedule that differs only by Lease-Level's TI / LC columns.
// =============================================================================

interface Reading {
  sections: (string | null)[];
  schedule: string[][];
}

function read(panel: HTMLElement): Reading {
  return {
    sections: ['Sources & Uses at Closing', 'Project Returns', 'Owner Cash Flow'].map(
      (name) => within(panel).getByRole('region', { name }).textContent,
    ),
    schedule: scheduleRows(panel),
  };
}

describe('the same result in every mode', () => {
  it(
    'reads identically in Quick, Detailed and Lease-Level',
    async () => {
      // Detailed and Lease-Level deliver the Quick V5 result through their own
      // envelopes, on a deal with the same Purchase Price.
      store.set(
        'detailed-ce',
        clone(detailedDeal({ ...DETAILED_ANALYSIS, results: QUICK_RESULTS })),
      );
      store.set('lease-ce', clone(leaseLevelDeal(QUICK.request.purchase_price)));
      leaseLevelAnswer = { ...LEASE_LEVEL_ANALYSIS, results: QUICK_RESULTS };

      let user = await launchAndOpen('Harbor Point');
      const quickReading = read(await openQuickOrDetailedCapitalEconomics(user));
      cleanup();

      user = await launchAndOpen('Canal Works');
      const detailedReading = read(await openQuickOrDetailedCapitalEconomics(user));
      cleanup();

      user = await launchAndOpen('Fulton Exchange');
      const leaseLevelReading = read(await analyzeLeaseLevelCapitalEconomics(user));

      expect(detailedReading).toEqual(quickReading);
      expect(leaseLevelReading.sections).toEqual(quickReading.sections);
      // Lease-Level's schedule is Quick's with TI and LC inserted after the
      // reserve -- the same periods, reserve, Project Capital and Owner Expenses.
      expect(
        leaseLevelReading.schedule.map((row) => [row[0], row[1], row[4], row[5]]),
      ).toEqual(quickReading.schedule);
    },
    // Three full open-and-navigate workflows in one test: a per-test budget,
    // not a file-wide one (protocol Section 10).
    20_000,
  );
});
