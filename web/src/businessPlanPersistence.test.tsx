/**
 * Phase 6 Gate D6.6 -- the Business Plan survives the web client.
 *
 * THE critical D6.6 invariant: the web client must never drop or clear a
 * persisted Business Plan because the analyst opened and saved the deal.
 *
 * **Nothing in `api.ts` is mocked.** The real `App` and the real client
 * functions run, and `fetch` itself is replaced by a small backend that holds
 * deals in a map and applies the D6.5 rule verbatim: a write whose body carries
 * no `business_plan` stores the EMPTY plan. So any omission anywhere between the
 * editor and the wire -- in App state, in a request builder, in `api.ts` --
 * clears the stored plan here exactly as it would against the real API, and the
 * preservation tests fail. They read the store, not a mock's call list.
 *
 * Presets and break-even are answered with a refusal. Their requests -- which
 * is what these tests read -- are still made; the risk panels simply show their
 * error state instead of needing full result fixtures.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import { referencePlan } from './businessPlanFixture';
import fixture from './leaseLevelResultsFixture.json';
import { ANALYSIS, clone, makeDeal as makeLeaseLevelDeal } from './leaseLevelDealFixture';
import {
  DEFAULT_FORM_VALUES,
  DETAILED_GOLDEN_FORM_VALUES,
  buildAcquisitionRequest,
  buildAcquisitionTermsRequest,
  buildDetailedOperatingInputsRequest,
} from './convert';
import { BUSINESS_PLAN_INCOMPLETE_MESSAGE } from './useBusinessPlan';
import { STALE_LABEL } from './components/StaleAnalysisNotice';
import type { BusinessPlanInput } from './businessPlan';
import type { Deal } from './types';
import type { LeaseLevelAcquisitionResults } from './leaseLevelTypes';

/**
 * Each test drives the whole application through a realistic workflow -- open,
 * edit, save, reopen after a refresh -- so one test does the work of a file of
 * component tests. Raised for this file only, as `leaseLevelAnalysisPersistence`
 * does: nothing waits on a timer, and a genuine hang still fails.
 */
vi.setConfig({ testTimeout: 30_000, hookTimeout: 30_000 });

const HEALTHY = fixture.healthy as unknown as LeaseLevelAcquisitionResults;
const QUICK_RESULTS = HEALTHY.results;

function five(value: number): number[] {
  return [value, value, value, value, value];
}

const DETAILED_RESULTS = {
  operating_projection: {
    gross_potential_rent_by_year: five(800_000),
    other_income_by_year: five(20_000),
    vacancy_credit_loss_by_year: five(41_000),
    effective_gross_income_by_year: five(779_000),
    property_taxes_by_year: five(60_000),
    insurance_by_year: five(20_000),
    utilities_by_year: five(25_000),
    repairs_maintenance_by_year: five(20_000),
    other_operating_expenses_by_year: five(16_000),
    management_fee_by_year: five(38_950),
    total_operating_expenses_by_year: five(179_950),
    noi_by_year: five(599_050),
    exit_noi: 599_050,
    going_in_cap_rate: 0.0599,
  },
  results: QUICK_RESULTS,
};

const EMPTY_PLAN: BusinessPlanInput = { capital_items: [], owner_expense_items: [] };

// =============================================================================
// The backend
// =============================================================================

interface Recorded {
  method: string;
  path: string;
  body: Record<string, unknown> | undefined;
}

const store = new Map<string, Deal>();
let requests: Recorded[] = [];
/** When set, `/analyze` refuses with this 422 detail. */
let analyzeRefusal: unknown[] | null = null;
let created = 0;

function reply(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => clone(body),
  } as Response;
}

const WRITABLE = [
  'name',
  'operating_mode',
  'inputs',
  'terms',
  'detailed_operating_inputs',
  'property_inputs',
  'operating_inputs',
  'market_leasing',
  'suites',
  'leases',
] as const;

/** One deal write, as D6.5 stores it. */
function written(existing: Record<string, unknown>, body: Record<string, unknown>): Deal {
  const next: Record<string, unknown> = { ...existing };
  for (const field of WRITABLE) {
    if (field in body) {
      next[field] = clone(body[field]);
    }
  }
  next.deal_context = body.deal_context ?? null;
  // The D6.5 rule, verbatim: absent (or null) is the EMPTY plan.
  next.business_plan = clone(body.business_plan ?? EMPTY_PLAN);
  next.updated_at = '2026-09-12T15:00:00+00:00';
  return next as unknown as Deal;
}

async function backend(url: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const path = String(url).replace('http://127.0.0.1:8000', '');
  const method = init?.method ?? 'GET';
  const body =
    typeof init?.body === 'string' ? (JSON.parse(init.body) as Record<string, unknown>) : undefined;
  requests.push({ method, path, body });

  const deal = /^\/deals\/([^/]+)$/.exec(path);
  if (method === 'GET' && path === '/deals') {
    return reply(200, [...store.values()]);
  }
  if (deal !== null && path !== '/deals/fingerprint') {
    const id = decodeURIComponent(deal[1]);
    const existing = store.get(id);
    if (existing === undefined) {
      return reply(404, { detail: 'not found' });
    }
    if (method === 'GET') {
      return reply(200, existing);
    }
    if (method === 'PUT') {
      store.set(id, written(existing as unknown as Record<string, unknown>, body ?? {}));
      return reply(200, store.get(id));
    }
  }
  if (method === 'POST' && path === '/deals') {
    created += 1;
    const id = `new-${created}`;
    const blank = {
      id,
      operating_mode: 'quick',
      inputs: null,
      terms: null,
      detailed_operating_inputs: null,
      property_inputs: null,
      operating_inputs: null,
      market_leasing: null,
      suites: null,
      leases: null,
      analysis_snapshot: null,
      ai_snapshot: null,
      one_way_sensitivity_snapshot: null,
      two_way_sensitivity_snapshot: null,
      created_at: '2026-09-12T15:00:00+00:00',
    };
    store.set(id, written(blank, body ?? {}));
    return reply(200, store.get(id));
  }
  if (path === '/deals/fingerprint') {
    return reply(200, { financial_input_fingerprint: 'fp', ai_context_fingerprint: 'fp-ai' });
  }
  const snapshot = /^\/deals\/([^/]+)\/(analysis-snapshot|ai-snapshot|sensitivity-snapshot)/.exec(path);
  if (method === 'PUT' && snapshot !== null) {
    return reply(200, store.get(decodeURIComponent(snapshot[1])));
  }
  if (path === '/analyze') {
    if (analyzeRefusal !== null) {
      return reply(422, { detail: analyzeRefusal });
    }
    if (body?.operating_mode === 'detailed') {
      return reply(200, DETAILED_RESULTS);
    }
    return reply(200, body?.operating_mode === 'lease_level' ? HEALTHY : QUICK_RESULTS);
  }
  if (path === '/ai/analysis') {
    return reply(200, ANALYSIS);
  }
  return reply(500, {});
}

function sent(path: string, method = 'POST'): Recorded[] {
  return requests.filter((request) => request.path === path && request.method === method);
}

function lastSent(path: string, method = 'POST'): Recorded {
  const matching = sent(path, method);
  expect(matching.length, `no ${method} ${path} was sent`).toBeGreaterThan(0);
  return matching[matching.length - 1];
}

// =============================================================================
// Deals
// =============================================================================

const TIMESTAMPS = {
  created_at: '2026-09-12T09:00:00+00:00',
  updated_at: '2026-09-12T09:00:00+00:00',
};

function quickDeal(): Deal {
  return {
    id: 'quick-1',
    name: 'Harbor Point',
    operating_mode: 'quick',
    inputs: buildAcquisitionRequest(DEFAULT_FORM_VALUES),
    terms: null,
    detailed_operating_inputs: null,
    property_inputs: null,
    operating_inputs: null,
    market_leasing: null,
    suites: null,
    leases: null,
    business_plan: referencePlan(),
    deal_context: null,
    analysis_snapshot: null,
    ai_snapshot: null,
    one_way_sensitivity_snapshot: null,
    two_way_sensitivity_snapshot: null,
    ...TIMESTAMPS,
  };
}

function detailedDeal(): Deal {
  return {
    ...quickDeal(),
    id: 'detailed-1',
    name: 'Canal Works',
    operating_mode: 'detailed',
    inputs: null,
    terms: buildAcquisitionTermsRequest(DETAILED_GOLDEN_FORM_VALUES.terms),
    detailed_operating_inputs: buildDetailedOperatingInputsRequest(
      DETAILED_GOLDEN_FORM_VALUES.operating,
    ),
  };
}

/** The shared Lease-Level fixture, on the same five-year hold as the other two
 * deals -- so month 61 is Post-Hold in every mode and the cross-mode comparison
 * below compares like with like. */
function leaseLevelDeal(): Deal {
  const base = makeLeaseLevelDeal('lease-1', 'Fulton Exchange');
  return {
    ...base,
    terms: { ...base.terms!, hold_period: 5 },
    business_plan: referencePlan(),
  };
}

beforeEach(() => {
  store.clear();
  requests = [];
  analyzeRefusal = null;
  created = 0;
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

async function launch(): Promise<User> {
  const user = userEvent.setup({ delay: null });
  render(<App />);
  await waitFor(() => expect(sent('/deals', 'GET').length).toBeGreaterThan(0));
  return user;
}

async function open(user: User, name: string): Promise<void> {
  const sidebar = await waitFor(() => {
    const list = document.querySelector('.sidebar-deal-list');
    expect(list).not.toBeNull();
    return list as HTMLElement;
  });
  await user.click(await within(sidebar).findByText(name));
  await waitFor(() => expect(screen.getByDisplayValue(name)).toBeTruthy());
  await waitFor(() => expect(document.querySelector('.business-plan')).not.toBeNull());
}

function field(id: string): HTMLInputElement {
  const element = document.getElementById(id);
  if (element === null) {
    throw new Error(`No field #${id}`);
  }
  return element as HTMLInputElement;
}

function labelled(label: string): HTMLInputElement {
  return screen.getByLabelText(label) as HTMLInputElement;
}

function descriptions(): string[] {
  return screen
    .getAllByLabelText(/^Description, /)
    .map((element) => (element as HTMLInputElement).value);
}

const REFERENCE_DESCRIPTIONS = [
  'Closing Improvements',
  'Unit Renovations',
  'Future Roof',
  'Asset Management',
  'Legal',
];

async function replaceValue(user: User, element: HTMLInputElement, value: string): Promise<void> {
  await user.clear(element);
  await user.type(element, value);
}

async function save(user: User): Promise<void> {
  const writes = requests.filter((request) => request.method !== 'GET').length;
  await user.click(screen.getByRole('button', { name: /^(Update Deal|Save Deal)$/ }));
  await waitFor(() =>
    expect(requests.filter((request) => request.method !== 'GET').length).toBeGreaterThan(writes),
  );
  await waitFor(() => expect(screen.getByRole('button', { name: 'Update Deal' })).toBeTruthy());
}

async function analyze(user: User): Promise<void> {
  const before = sent('/analyze').length;
  await user.click(screen.getByRole('button', { name: /^Analyze/ }));
  await waitFor(() => expect(sent('/analyze').length).toBeGreaterThan(before));
}

/** Fills Quick's fourteen assumptions by id, exactly as typing would. */
function fillQuick(): void {
  for (const [key, value] of Object.entries(DEFAULT_FORM_VALUES)) {
    fireEvent.change(field(key), { target: { value } });
  }
}

// =============================================================================
// U5 / PART AO -- an API-created plan survives an unrelated web save
// =============================================================================

describe('an API-created Business Plan survives an unrelated web save (PART AO)', () => {
  it('Quick: hydrates every row exactly, and saving an unrelated field leaves it byte-identical', async () => {
    const user = await launch();
    await open(user, 'Harbor Point');

    expect(descriptions()).toEqual(REFERENCE_DESCRIPTIONS);
    expect(labelled('Model Month, Closing Improvements').value).toBe('0');
    expect(labelled('Model Month, Unit Renovations').value).toBe('18');
    expect(labelled('Model Month, Future Roof').value).toBe('61');
    expect(labelled('Amount, Unit Renovations').value).toBe('1,000,000');
    expect(labelled('Annual Amount, Asset Management').value).toBe('50,000');
    expect(labelled('Last Year, Asset Management').value).toBe('');
    expect(labelled('Last Year, Legal').value).toBe('3');
    expect((labelled('Category, Future Roof') as unknown as HTMLSelectElement).value).toBe(
      'deferred_maintenance',
    );
    expect(screen.getByText('Post-Hold')).toBeTruthy();

    await replaceValue(user, field('purchasePrice'), '52000000');
    await save(user);

    const put = lastSent('/deals/quick-1', 'PUT');
    expect(put.body?.business_plan).toEqual(referencePlan());
    const stored = store.get('quick-1')!;
    expect(stored.inputs?.purchase_price).toBe(52_000_000);
    expect(JSON.stringify(stored.business_plan)).toBe(JSON.stringify(referencePlan()));

    // A refresh: nothing survives but the store.
    cleanup();
    const again = await launch();
    await open(again, 'Harbor Point');
    expect(descriptions()).toEqual(REFERENCE_DESCRIPTIONS);
  });

  it('Lease-Level: the same plan survives an unrelated save, and is sent with the whole rent roll', async () => {
    const user = await launch();
    await open(user, 'Fulton Exchange');
    expect(descriptions()).toEqual(REFERENCE_DESCRIPTIONS);

    await replaceValue(user, field('lease-level-terms-purchasePrice'), '31000000');
    await save(user);

    const put = lastSent('/deals/lease-1', 'PUT');
    expect(put.body?.business_plan).toEqual(referencePlan());
    expect(put.body?.suites).toEqual(leaseLevelDeal().suites);
    const stored = store.get('lease-1')!;
    expect(stored.terms?.purchase_price).toBe(31_000_000);
    expect(JSON.stringify(stored.business_plan)).toBe(JSON.stringify(referencePlan()));
  });

  it('Detailed: the same plan survives an unrelated save', async () => {
    const user = await launch();
    await open(user, 'Canal Works');
    expect(descriptions()).toEqual(REFERENCE_DESCRIPTIONS);

    await replaceValue(user, field('purchasePrice'), '10500000');
    await save(user);

    expect(lastSent('/deals/detailed-1', 'PUT').body?.business_plan).toEqual(referencePlan());
    expect(JSON.stringify(store.get('detailed-1')!.business_plan)).toBe(
      JSON.stringify(referencePlan()),
    );
  });

  it('a rename alone -- no assumption touched -- still sends the plan', async () => {
    const user = await launch();
    await open(user, 'Harbor Point');
    await replaceValue(user, labelled('Deal Name'), 'Harbor Point II');
    await save(user);
    expect(store.get('quick-1')!.business_plan).toEqual(referencePlan());
  });
});

// =============================================================================
// U6 / PART AP -- an intentional clear
// =============================================================================

describe('removing every row intentionally clears the plan (PART AP)', () => {
  it.each([
    ['Harbor Point', 'quick-1'],
    ['Fulton Exchange', 'lease-1'],
  ])('%s: saves an explicitly empty plan, and reopens empty', async (name, id) => {
    const user = await launch();
    await open(user, name);
    for (const button of screen.getAllByRole('button', { name: /^Remove / })) {
      await user.click(button);
    }
    expect(screen.getByText('Unsaved changes')).toBeTruthy();
    await save(user);

    expect(lastSent(`/deals/${id}`, 'PUT').body?.business_plan).toEqual(EMPTY_PLAN);
    expect(store.get(id)!.business_plan).toEqual(EMPTY_PLAN);

    cleanup();
    const again = await launch();
    await open(again, name);
    expect(screen.getByText('No project capital scheduled.')).toBeTruthy();
    expect(screen.getByText('No owner expenses.')).toBeTruthy();
  });
});

// =============================================================================
// U7-U9 / PART S, U, V -- every analytical request carries the plan
// =============================================================================

describe('every analytical request carries the current plan (PART S, U, V)', () => {
  it('Quick: analyze, sensitivity, break-even, fingerprint and the AI Analyst', async () => {
    const user = await launch();
    await open(user, 'Harbor Point');
    await analyze(user);

    expect(lastSent('/analyze').body).toEqual({
      ...buildAcquisitionRequest(DEFAULT_FORM_VALUES),
      business_plan: referencePlan(),
    });
    await waitFor(() => expect(sent('/break-even').length).toBe(1));
    expect(lastSent('/sensitivity/presets').body?.business_plan).toEqual(referencePlan());
    expect(lastSent('/break-even').body?.business_plan).toEqual(referencePlan());
    // The saved, unedited deal refreshes its analysis snapshot: the provenance
    // token is fetched for the same plan the analysis ran on.
    await waitFor(() => expect(sent('/deals/fingerprint').length).toBeGreaterThan(0));
    expect(lastSent('/deals/fingerprint').body?.business_plan).toEqual(referencePlan());

    await user.click(screen.getByRole('tab', { name: 'AI Analyst' }));
    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));
    await waitFor(() => expect(sent('/ai/analysis').length).toBe(1));
    expect(lastSent('/ai/analysis').body?.business_plan).toEqual(referencePlan());
  });

  it('Detailed: analyze, sensitivity and break-even', async () => {
    const user = await launch();
    await open(user, 'Canal Works');
    await analyze(user);
    expect(lastSent('/analyze').body).toMatchObject({
      operating_mode: 'detailed',
      business_plan: referencePlan(),
    });
    await waitFor(() => expect(sent('/break-even').length).toBe(1));
    expect(lastSent('/sensitivity/presets').body?.business_plan).toEqual(referencePlan());
    expect(lastSent('/break-even').body?.business_plan).toEqual(referencePlan());
  });

  it('Lease-Level: analyze, the AI Analyst and the snapshot fingerprint', async () => {
    const user = await launch();
    await open(user, 'Fulton Exchange');
    await analyze(user);
    expect(lastSent('/analyze').body).toMatchObject({
      operating_mode: 'lease_level',
      business_plan: referencePlan(),
    });

    await user.click(screen.getByRole('tab', { name: 'AI Analyst' }));
    await user.click(screen.getByRole('button', { name: /Generate AI Analysis/ }));
    await waitFor(() => expect(sent('/ai/analysis').length).toBe(1));
    expect(lastSent('/ai/analysis').body?.business_plan).toEqual(referencePlan());
    await waitFor(() => expect(sent('/deals/fingerprint').length).toBeGreaterThan(0));
    expect(lastSent('/deals/fingerprint').body?.business_plan).toEqual(referencePlan());
  });

  it('a new deal sends an explicitly empty plan (U1)', async () => {
    store.clear();
    const user = await launch();
    fillQuick();
    await analyze(user);
    expect(lastSent('/analyze').body?.business_plan).toEqual(EMPTY_PLAN);
  });
});

// =============================================================================
// U2-U4 / PART K, L -- new rows: stable IDs and exact serialization
// =============================================================================

async function addCapital(user: User, description: string, category: string, month: string, amount: string) {
  await user.click(screen.getByRole('button', { name: 'Add Project Capital' }));
  await user.type(labelled('Description, new Project Capital item'), description);
  await user.selectOptions(screen.getByLabelText(`Category, ${description}`), category);
  await user.type(labelled(`Model Month, ${description}`), month);
  await user.type(labelled(`Amount, ${description}`), amount);
}

async function addOwnerExpense(
  user: User,
  description: string,
  category: string,
  annualAmount: string,
  firstYear: string,
  lastYear: string,
) {
  await user.click(screen.getByRole('button', { name: 'Add Owner Expense' }));
  await user.type(labelled('Description, new Owner Expense item'), description);
  await user.selectOptions(screen.getByLabelText(`Category, ${description}`), category);
  await user.type(labelled(`Annual Amount, ${description}`), annualAmount);
  await user.type(labelled(`First Year, ${description}`), firstYear);
  if (lastYear !== '') {
    await user.type(labelled(`Last Year, ${description}`), lastYear);
  }
}

describe('a plan entered in the editor (U2-U4, PART K, L)', () => {
  it('serializes exactly, keeps every ID through typing, analysis and saves, and never collides', async () => {
    store.clear();
    const user = await launch();
    fillQuick();
    await addCapital(user, 'Closing Building Systems', 'building_systems', '0', '250000');
    await addCapital(user, 'Unit Renovation Program', 'value_add_renovation', '18', '1000000');
    await addCapital(user, 'Future Roof Replacement', 'deferred_maintenance', '61', '500000');
    await addOwnerExpense(user, 'Asset Management', 'asset_management', '50000', '1', '');
    await addOwnerExpense(user, 'Legal / Partnership', 'legal_partnership', '15000', '2', '3');

    expect(screen.getByText('Closing')).toBeTruthy();
    expect(screen.getByText('Year 2')).toBeTruthy();
    expect(screen.getByText('Post-Hold')).toBeTruthy();

    await user.type(labelled('Deal Name'), 'Entered Plan');
    await save(user);
    const first = lastSent('/deals').body?.business_plan as BusinessPlanInput;
    expect(first.capital_items.map(({ month, amount, category }) => [month, amount, category])).toEqual([
      [0, 250000, 'building_systems'],
      [18, 1000000, 'value_add_renovation'],
      [61, 500000, 'deferred_maintenance'],
    ]);
    expect(first.owner_expense_items.map(({ first_year, last_year, annual_amount }) => [first_year, last_year, annual_amount])).toEqual([
      [1, null, 50000],
      [2, 3, 15000],
    ]);
    const ids = [
      ...first.capital_items.map((item) => item.item_id),
      ...first.owner_expense_items.map((item) => item.item_id),
    ];
    expect(new Set(ids).size).toBe(5);
    expect(ids.every((id) => id.length > 0)).toBe(true);

    // Typing, analysis and a second save move no ID and no row.
    await replaceValue(user, labelled('Description, Unit Renovation Program'), 'Unit Renovations');
    await analyze(user);
    const analyzed = lastSent('/analyze').body?.business_plan as BusinessPlanInput;
    await user.click(screen.getByRole('tab', { name: 'Underwrite' }));
    await save(user);
    const second = lastSent('/deals/new-1', 'PUT').body?.business_plan as BusinessPlanInput;
    for (const plan of [analyzed, second]) {
      expect([
        ...plan.capital_items.map((item) => item.item_id),
        ...plan.owner_expense_items.map((item) => item.item_id),
      ]).toEqual(ids);
    }
    expect(second.capital_items[1].description).toBe('Unit Renovations');
    expect(store.get('new-1')!.business_plan).toEqual(second);
  });
});

// =============================================================================
// PART AL, AK -- through hold, and a hold change
// =============================================================================

describe('changing the hold period changes labels, never stored values (PART AK, AL)', () => {
  it('keeps last_year null and month 61, and reclassifies only the tag', async () => {
    const user = await launch();
    await open(user, 'Harbor Point');
    expect(screen.getByText('Post-Hold')).toBeTruthy();

    await replaceValue(user, field('holdPeriod'), '7');
    expect(screen.queryByText('Post-Hold')).toBeNull();
    expect(screen.getByText('Year 6')).toBeTruthy();
    await save(user);

    const stored = store.get('quick-1')!;
    expect(stored.inputs?.hold_period).toBe(7);
    expect(stored.business_plan.owner_expense_items[0].last_year).toBeNull();
    expect(stored.business_plan.capital_items[2].month).toBe(61);
  });
});

// =============================================================================
// U10 / PART O, P -- validation
// =============================================================================

describe('validation keeps the draft and sends nothing (U10, PART O, P)', () => {
  it('refuses an invalid row inline, retains every value, and neither analyzes nor saves', async () => {
    store.clear();
    const user = await launch();
    fillQuick();
    await user.click(screen.getByRole('button', { name: 'Add Project Capital' }));
    await user.type(labelled('Model Month, new Project Capital item'), '1.5');
    await user.type(labelled('Amount, new Project Capital item'), '-5');

    await user.click(screen.getByRole('button', { name: /^Analyze/ }));
    expect(await screen.findByText(BUSINESS_PLAN_INCOMPLETE_MESSAGE)).toBeTruthy();
    expect(screen.getByText('Enter a description.')).toBeTruthy();
    expect(screen.getByText('Select a category.')).toBeTruthy();
    expect(screen.getByText('Model Month must be a whole number.')).toBeTruthy();
    expect(screen.getByText('Amount must be 0 or greater.')).toBeTruthy();
    expect(labelled('Model Month, new Project Capital item').value).toBe('1.5');
    expect(labelled('Amount, new Project Capital item').value).toBe('-5');
    expect(labelled('Amount, new Project Capital item').getAttribute('aria-invalid')).toBe('true');

    await user.click(screen.getByRole('button', { name: 'Save Deal' }));
    expect(sent('/analyze')).toEqual([]);
    expect(sent('/deals')).toEqual([]);

    // Fixing the row lets the same deal through.
    await user.type(labelled('Description, new Project Capital item'), 'Lobby');
    await user.selectOptions(screen.getByLabelText('Category, Lobby'), 'other');
    await replaceValue(user, labelled('Model Month, Lobby'), '6');
    await replaceValue(user, labelled('Amount, Lobby'), '0');
    expect(screen.queryByText('Enter a description.')).toBeNull();
    await analyze(user);
    expect(lastSent('/analyze').body?.business_plan).toMatchObject({
      capital_items: [{ description: 'Lobby', category: 'other', month: 6, amount: 0 }],
    });
  });

  it('places a backend 422 on its row, keeps the draft, and puts the section on screen', async () => {
    const user = await launch();
    await open(user, 'Harbor Point');
    analyzeRefusal = [
      {
        code: 'AMOUNT_OUT_OF_DOMAIN',
        path: 'business_plan.capital_items[1].amount',
        message: 'amount 1000000.0 must be greater than or equal to 0.',
      },
    ];
    await user.click(screen.getByRole('button', { name: /^Analyze/ }));
    const message = await screen.findAllByText('amount 1000000.0 must be greater than or equal to 0.');
    expect(message.length).toBeGreaterThan(0);
    const amount = labelled('Amount, Unit Renovations');
    expect(amount.getAttribute('aria-invalid')).toBe('true');
    expect(document.getElementById(amount.getAttribute('aria-describedby')!)?.textContent).toBe(
      'amount 1000000.0 must be greater than or equal to 0.',
    );
    expect(amount.value).toBe('1,000,000');
    expect(descriptions()).toEqual(REFERENCE_DESCRIPTIONS);
  });
});

// =============================================================================
// PART Y -- the plan joins the existing dirty and out-of-date behaviour
// =============================================================================

describe('a plan edit is an underwriting edit (PART Y)', () => {
  it('Quick: marks the deal unsaved and drops the analysis, like any assumption', async () => {
    const user = await launch();
    await open(user, 'Harbor Point');
    expect(screen.getByText(/^Saved/)).toBeTruthy();
    await analyze(user);
    await user.click(screen.getByRole('tab', { name: 'Underwrite' }));
    expect(screen.queryByText('Analyze the deal to populate live metrics.')).toBeNull();

    await replaceValue(user, labelled('Amount, Future Roof'), '650000');
    expect(screen.getByText('Unsaved changes')).toBeTruthy();
    expect(screen.getByText('Analyze the deal to populate live metrics.')).toBeTruthy();
  });

  it('Lease-Level: an AI report goes out of date on a plan edit, and current again on revert', async () => {
    const user = await launch();
    await open(user, 'Fulton Exchange');
    await analyze(user);
    await user.click(screen.getByRole('tab', { name: 'AI Analyst' }));
    await user.click(screen.getByRole('button', { name: /Generate AI Analysis/ }));
    await waitFor(() => expect(sent('/ai/analysis').length).toBe(1));
    const aiPanel = document.getElementById('workspace-panel-ai')!;
    await waitFor(() => expect(within(aiPanel).getByText(ANALYSIS.executive_summary)).toBeTruthy());
    expect(within(aiPanel).queryByText(STALE_LABEL)).toBeNull();

    await user.click(screen.getByRole('tab', { name: 'Underwrite' }));
    await user.click(screen.getByRole('tab', { name: 'Acquisition & Debt' }));
    await replaceValue(user, labelled('Annual Amount, Legal'), '20000');
    expect(within(aiPanel).getByText(STALE_LABEL)).toBeTruthy();

    await replaceValue(user, labelled('Annual Amount, Legal'), '15000');
    expect(within(aiPanel).queryByText(STALE_LABEL)).toBeNull();
  });
});

// =============================================================================
// PART AQ, AR -- one editor in every mode, apart from TI / LC
// =============================================================================

describe('one editor, the same in every mode (PART AQ, AR)', () => {
  function editorCopy(): string {
    return document.querySelector('.business-plan')?.textContent ?? '';
  }

  it('renders the same labels and semantics in Quick, Detailed and Lease-Level', async () => {
    const copies: string[] = [];
    for (const name of ['Harbor Point', 'Canal Works', 'Fulton Exchange']) {
      const user = await launch();
      await open(user, name);
      expect(document.querySelectorAll('.business-plan')).toHaveLength(1);
      copies.push(editorCopy());
      cleanup();
    }
    const [quick, detailed, leaseLevel] = copies;
    expect(detailed, 'Detailed renders a different Business Plan editor').toBe(quick);
    expect(leaseLevel, 'Lease-Level renders a different Business Plan editor').toBe(quick);
  });

  it('keeps Lease-Level Project Capital on Acquisition & Debt, apart from the rent roll and market leasing', async () => {
    const user = await launch();
    await open(user, 'Fulton Exchange');
    const editor = document.querySelector('.business-plan')!;
    expect(editor.closest('#lease-level-panel-acquisition')).not.toBeNull();
    expect(document.querySelector('#lease-level-panel-rent-roll .business-plan')).toBeNull();
    expect(document.querySelector('#lease-level-panel-market .business-plan')).toBeNull();
    expect(editor.textContent).toContain(
      'Separate from the recurring CapEx Reserve and from tenant improvements and leasing commissions.',
    );
    void user;
  });
});
