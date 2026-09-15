/**
 * Phase 7 Gate P7.6 -- Deals and Investments in the one application shell.
 *
 * Driven through `App` against a mocked `api.ts`: the sidebar offers both,
 * each with its own library; a visible Investment opens its own workspace; a
 * Unit opens in its own, existing Deal workspace with a way back that re-reads
 * the Investment; and a Deal that is a Unit points to its Investment rather
 * than calling routes that refuse it.
 *
 * An open Strategy or Scenario draft on the Investment is never lost silently:
 * it survives a Unit visit exactly as typed (the Investment's decision tools
 * stay mounted, hidden, under their own id namespace), and opening a different
 * Investment -- the one move that unmounts it -- asks first.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import {
  createVisibleInvestment,
  fetchScenarioTargetCatalog,
  getDeal,
  getVisibleInvestment,
  listDealScenarios,
  listDealStrategies,
  listDeals,
  listVisibleInvestments,
} from './api';
import { UNIT_OF_INVESTMENT_NOTICE } from './investmentCatalog';
import type { VisibleInvestment } from './investmentTypes';
import type { AcquisitionRequest, Deal } from './types';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    listDeals: vi.fn(),
    getDeal: vi.fn(),
    listVisibleInvestments: vi.fn(),
    getVisibleInvestment: vi.fn(),
    createVisibleInvestment: vi.fn(),
    promoteHiddenInvestment: vi.fn(),
    analyzeInvestmentVariant: vi.fn(),
    listInvestmentStrategies: vi.fn(async () => []),
    listInvestmentScenarios: vi.fn(async () => []),
    listDealScenarios: vi.fn(async (dealId: string) => ({ deal_id: dealId, investment_id: null, scenarios: [] })),
    listDealStrategies: vi.fn(async (dealId: string) => ({ deal_id: dealId, investment_id: null, strategies: [] })),
    fetchScenarioTargetCatalog: vi.fn(),
    fetchStrategyTargetCatalog: vi.fn(async () => ({ quick: [], detailed: [], lease_level: [] })),
  };
});

const INPUTS: AcquisitionRequest = {
  purchase_price: 12_500_000,
  current_noi: 800_000,
  occupancy: 0.94,
  noi_growth: 0.03,
  hold_period: 5,
  exit_cap_rate: 0.0625,
  ltv: 0.65,
  interest_rate: 0.0575,
  amortization: 30,
  acquisition_cost_pct: 0.02,
  financing_fee_pct: 0.01,
  disposition_cost_pct: 0.02,
  annual_capex_reserve: 40_000,
  io_period: 2,
};

function quickDeal(id: string, name: string, price: number, savedAt = `${id}-saved`): Deal {
  return {
    id,
    name,
    operating_mode: 'quick',
    inputs: { ...INPUTS, purchase_price: price },
    terms: null,
    detailed_operating_inputs: null,
    property_inputs: null,
    operating_inputs: null,
    market_leasing: null,
    suites: null,
    leases: null,
    business_plan: { capital_items: [], owner_expense_items: [] },
    deal_context: null,
    analysis_snapshot: null,
    ai_snapshot: null,
    one_way_sensitivity_snapshot: null,
    two_way_sensitivity_snapshot: null,
    created_at: '2026-09-14T00:00:00+00:00',
    updated_at: savedAt,
  } as unknown as Deal;
}

const RETAIL = quickDeal('deal-a', 'Harbor Retail', 12_500_000);
const OFFICE = quickDeal('deal-b', 'Harbor Office', 20_000_000);
const FLEX = quickDeal('deal-d', 'Bayside Flex', 8_000_000);

const INVESTMENT: VisibleInvestment = {
  id: 'inv-1',
  name: 'Harbor Portfolio',
  transaction_price: 32_500_000,
  units: [
    { unit_id: 'deal-a', ordinal: 0, label: null, unit_kind: 'property', acquisition_month: 0, disposition_month: null },
    { unit_id: 'deal-b', ordinal: 1, label: null, unit_kind: 'property', acquisition_month: 0, disposition_month: null },
  ],
  business_plan: { capital_items: [], owner_expense_items: [] },
  transaction_costs: [],
  created_at: '2026-09-14T00:00:00+00:00',
  updated_at: '2026-09-14T00:00:00+00:00',
};

const SCENARIO_CATALOG = {
  quick: [{ target: 'exit_cap_rate', allowed_operations: ['set', 'add'], units: 'decimal rate (0.0725 is 7.25%)' }],
  detailed: [],
  lease_level: [],
};

function serve(deals: Deal[]) {
  vi.mocked(listDeals).mockResolvedValue(deals);
  vi.mocked(getDeal).mockImplementation(async (id) => deals.find((deal) => deal.id === id) as Deal);
}

beforeEach(() => {
  serve([RETAIL, OFFICE, FLEX]);
  vi.mocked(listVisibleInvestments).mockResolvedValue([INVESTMENT]);
  vi.mocked(getVisibleInvestment).mockResolvedValue(INVESTMENT);
  vi.mocked(fetchScenarioTargetCatalog).mockResolvedValue(
    SCENARIO_CATALOG as unknown as Awaited<ReturnType<typeof fetchScenarioTargetCatalog>>,
  );
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function sidebar(): HTMLElement {
  return screen.getByRole('navigation', { name: 'Anchor navigation' });
}

async function openFromSidebar(user: ReturnType<typeof userEvent.setup>) {
  const recent = await within(sidebar()).findByRole('list', { name: 'Recent Investments' });
  await user.click(await within(recent).findByRole('button', { name: /Harbor Portfolio/ }));
  return screen.findByRole('heading', { name: 'Harbor Portfolio', level: 1 });
}

function investmentTab(name: 'Overview' | 'Units' | 'Risk'): HTMLElement {
  return within(screen.getByRole('tablist', { name: 'Investment workspace' })).getByRole('tab', { name });
}

function riskViewTab(name: 'Decision Matrix' | 'Strategies' | 'Scenarios'): HTMLElement {
  return within(screen.getByRole('tablist', { name: 'Investment risk views' })).getByRole('tab', { name });
}

async function openRiskView(user: ReturnType<typeof userEvent.setup>, name: 'Strategies' | 'Scenarios') {
  await user.click(investmentTab('Risk'));
  await user.click(riskViewTab(name));
}

/** Units -> Open Underwriting: the Unit opens in its own Deal workspace. */
async function openUnit(user: ReturnType<typeof userEvent.setup>, dealName: string) {
  await user.click(investmentTab('Units'));
  await user.click(await screen.findByRole('button', { name: `Open underwriting for ${dealName}` }));
  await waitFor(() => expect((screen.getByLabelText('Deal Name') as HTMLInputElement).value).toBe(dealName));
}

async function backToInvestment(user: ReturnType<typeof userEvent.setup>) {
  const breadcrumb = screen.getByRole('navigation', { name: 'Investment breadcrumb' });
  await user.click(within(breadcrumb).getByRole('button', { name: /Back to Investment/ }));
  await screen.findByRole('heading', { name: 'Harbor Portfolio', level: 1 });
}

/** Every element id the document holds more than once. */
function duplicateIds(): string[] {
  const counts = new Map<string, number>();
  for (const element of document.querySelectorAll('[id]')) {
    counts.set(element.id, (counts.get(element.id) ?? 0) + 1);
  }
  return [...counts].filter(([, count]) => count > 1).map(([id]) => id);
}

/** Every id an ARIA relationship inside the Investment names, with none
 * missing from the document. */
function danglingReferences(): string[] {
  const host = document.querySelector('.investment-host');
  if (host === null) {
    return [];
  }
  const missing: string[] = [];
  for (const attribute of ['aria-labelledby', 'aria-controls', 'aria-describedby']) {
    for (const element of host.querySelectorAll(`[${attribute}]`)) {
      for (const id of (element.getAttribute(attribute) ?? '').split(' ').filter((token) => token !== '')) {
        if (document.getElementById(id) === null) {
          missing.push(`${attribute}=${id}`);
        }
      }
    }
  }
  return missing;
}

/** An open editor, control by control: each field's id and value, each radio's
 * group, value and whether it is chosen. */
function draftFields(editorId: string): string[][] {
  const editor = document.getElementById(editorId);
  if (editor === null) {
    throw new Error(`No open editor ${editorId}`);
  }
  return [...editor.querySelectorAll<HTMLInputElement | HTMLSelectElement>('input, select')].map((control) =>
    control instanceof HTMLInputElement && control.type === 'radio'
      ? [`${control.name}=${control.value}`, String(control.checked)]
      : [control.id, control.value],
  );
}

describe('Deals and Investments side by side', () => {
  it('offers both in the sidebar, each with its own library', async () => {
    const user = userEvent.setup();
    render(<App />);
    const nav = sidebar();
    for (const name of ['Deal Library', 'New Deal', 'Investment Library', 'New Investment']) {
      expect(within(nav).getByRole('button', { name })).toBeTruthy();
    }
    expect(within(nav).getByText('Recent Deals')).toBeTruthy();
    expect(within(nav).getByText('Recent Investments')).toBeTruthy();
    const recent = await within(nav).findByRole('list', { name: 'Recent Investments' });
    expect(await within(recent).findByText('2 Units · $32,500,000')).toBeTruthy();

    await user.click(within(nav).getByRole('button', { name: 'Investment Library' }));
    expect(await screen.findByRole('heading', { name: 'Investment Library' })).toBeTruthy();
    expect(within(nav).getByRole('button', { name: 'Investment Library' }).getAttribute('aria-current')).toBe('page');
    await user.click(screen.getByRole('button', { name: 'Open Harbor Portfolio' }));
    expect(await screen.findByRole('heading', { name: 'Harbor Portfolio', level: 1 })).toBeTruthy();

    // The Deal Library is unchanged and separate.
    await user.click(within(nav).getByRole('button', { name: 'Deal Library' }));
    expect(await screen.findByRole('heading', { name: 'Deal Library' })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Harbor Portfolio', level: 1 })).toBeNull();
  });

  it('opens a Unit in its own Deal workspace and comes back to a re-read Investment', async () => {
    const user = userEvent.setup();
    render(<App />);
    await openFromSidebar(user);
    expect(getVisibleInvestment).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('tab', { name: 'Units' }));
    await user.click(await screen.findByRole('button', { name: 'Open underwriting for Harbor Retail' }));

    await waitFor(() => expect((screen.getByLabelText('Deal Name') as HTMLInputElement).value).toBe('Harbor Retail'));
    expect(getDeal).toHaveBeenCalledWith('deal-a');
    const breadcrumb = screen.getByRole('navigation', { name: 'Investment breadcrumb' });
    expect(within(breadcrumb).getByText('Harbor Portfolio')).toBeTruthy();

    // The Unit's own decision set lives on the Investment: it points there and
    // asks nothing of the Deal-scoped routes, which would refuse it.
    await user.click(screen.getByRole('tab', { name: 'Risk' }));
    expect((await screen.findAllByText(UNIT_OF_INVESTMENT_NOTICE)).length).toBeGreaterThan(0);
    expect(listDealStrategies).not.toHaveBeenCalled();
    expect(listDealScenarios).not.toHaveBeenCalled();
    // The hidden Investment keeps its decision tools mounted -- and so its
    // drafts -- under its own id namespace: the Deal's Risk ids stay the
    // Deal's, unique, and no id anywhere is duplicated.
    for (const id of ['risk-panel-matrix', 'risk-panel-strategies', 'risk-panel-scenarios', 'risk-tab-matrix']) {
      expect(document.querySelectorAll(`#${id}`), id).toHaveLength(1);
    }
    for (const id of ['investment-risk-panel-matrix', 'investment-risk-panel-strategies', 'investment-risk-tab-matrix']) {
      expect(document.querySelectorAll(`#${id}`), id).toHaveLength(1);
    }
    expect(duplicateIds()).toEqual([]);
    expect(danglingReferences()).toEqual([]);

    await user.click(within(breadcrumb).getByRole('button', { name: /Back to Investment/ }));
    expect(await screen.findByRole('heading', { name: 'Harbor Portfolio', level: 1 })).toBeTruthy();
    await waitFor(() => expect(getVisibleInvestment).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole('navigation', { name: 'Investment breadcrumb' })).toBeNull();
  });

  it('builds a New Investment from the sidebar and opens it', async () => {
    const user = userEvent.setup();
    vi.mocked(createVisibleInvestment).mockResolvedValue({ ...INVESTMENT, id: 'inv-2', name: 'Bayside Single' });
    vi.mocked(getVisibleInvestment).mockResolvedValue({ ...INVESTMENT, id: 'inv-2', name: 'Bayside Single' });
    render(<App />);
    await user.click(within(sidebar()).getByRole('button', { name: 'New Investment' }));
    expect(await screen.findByRole('heading', { name: 'New Investment' })).toBeTruthy();
    await user.type(screen.getByLabelText('Investment Name'), 'Bayside Single');
    await user.type(screen.getByLabelText('Transaction Price'), '8000000');
    await user.click(await screen.findByRole('checkbox', { name: 'Include Bayside Flex' }));
    await waitFor(() => expect((screen.getByRole('button', { name: 'Create Investment' }) as HTMLButtonElement).disabled).toBe(false));
    await user.click(screen.getByRole('button', { name: 'Create Investment' }));
    await waitFor(() => expect(createVisibleInvestment).toHaveBeenCalledTimes(1));
    expect(vi.mocked(createVisibleInvestment).mock.calls[0][0].units).toEqual([
      { unit_id: 'deal-d', label: null, unit_kind: 'property' },
    ]);
    expect(await screen.findByRole('heading', { name: 'Bayside Single', level: 1 })).toBeTruthy();
    expect(getVisibleInvestment).toHaveBeenCalledWith('inv-2');
  });
});

describe('an Investment’s open decision drafts are never lost silently', () => {
  it('keeps a Strategy draft exactly as typed through Open Underwriting and back, against the re-read Unit', async () => {
    const user = userEvent.setup();
    render(<App />);
    await openFromSidebar(user);
    await openRiskView(user, 'Strategies');
    await user.click(await screen.findByRole('button', { name: 'Add Strategy' }));
    await user.type(screen.getByLabelText('Strategy Name'), 'Hold Longer');
    await user.type(screen.getByLabelText('Description (optional)'), 'Seven years on Retail');
    const retail = screen.getByRole('region', { name: 'Harbor Retail' });
    const specific = within(within(retail).getByRole('radiogroup', { name: 'Disposition' })).getByRole('radio', {
      name: 'Strategy-specific',
    }) as HTMLInputElement;
    await waitFor(() => expect(specific.disabled).toBe(false));
    await user.click(specific);
    await user.click(within(retail).getByLabelText('Hold Period'));
    await user.keyboard('{Control>}a{/Control}7');
    // Acquisition still inherits Harbor Retail's saved Base.
    expect(within(retail).getByText(/\$12,500,000/)).toBeTruthy();
    const typed = draftFields('investment-strategy-editor');
    expect(typed).toContainEqual(['investment-strategy-editor-name', 'Hold Longer']);
    expect(typed).toContainEqual(['investment-strategy-u0-disposition-holdPeriod', '7']);

    await openUnit(user, 'Harbor Retail');
    expect(duplicateIds()).toEqual([]);
    expect(danglingReferences()).toEqual([]);
    // Harbor Retail is saved at a new price while its underwriting is open.
    serve([quickDeal('deal-a', 'Harbor Retail', 13_000_000, 'deal-a-saved-2'), OFFICE, FLEX]);
    const dealReads = vi.mocked(getDeal).mock.calls.length;
    await backToInvestment(user);

    // Coming back re-reads the Investment, its Units and the moved Unit's Base ...
    await waitFor(() => expect(getVisibleInvestment).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(vi.mocked(getDeal).mock.calls.slice(dealReads)).toContainEqual(['deal-a']));
    await user.click(investmentTab('Risk'));
    expect(riskViewTab('Strategies').getAttribute('aria-selected')).toBe('true');
    const back = screen.getByRole('region', { name: 'Harbor Retail' });
    expect(await within(back).findByText(/\$13,000,000/)).toBeTruthy();
    // ... and the draft is the one the analyst typed, field for field.
    expect(draftFields('investment-strategy-editor')).toEqual(typed);
    expect((screen.getByRole('button', { name: 'Save Strategy' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('keeps a Scenario draft exactly as typed through Open Underwriting and back', async () => {
    const user = userEvent.setup();
    render(<App />);
    await openFromSidebar(user);
    await openRiskView(user, 'Scenarios');
    await user.click(await screen.findByRole('button', { name: 'Add Scenario' }));
    await user.type(screen.getByLabelText('Scenario Name'), 'Office Downside');
    await user.type(screen.getByLabelText('Description (optional)'), 'Softer exit');
    await user.selectOptions(screen.getByLabelText('Unit', { exact: true }), 'deal-b');
    await user.selectOptions(screen.getByLabelText('Assumption', { exact: true }), 'exit_cap_rate');
    await user.selectOptions(screen.getByLabelText(/^Operation/), 'add');
    await user.type(screen.getByLabelText(/^Value/), '0.5');
    const typed = draftFields('investment-scenario-editor');
    expect(typed).toContainEqual(['investment-scenario-editor-name', 'Office Downside']);
    expect(typed).toContainEqual(['investment-override-row-1-unit', 'deal-b']);
    expect(typed).toContainEqual(['investment-override-row-1-value', '0.5']);

    await openUnit(user, 'Harbor Office');
    expect(duplicateIds()).toEqual([]);
    expect(danglingReferences()).toEqual([]);
    await backToInvestment(user);

    await waitFor(() => expect(getVisibleInvestment).toHaveBeenCalledTimes(2));
    await user.click(investmentTab('Risk'));
    expect(riskViewTab('Scenarios').getAttribute('aria-selected')).toBe('true');
    expect(draftFields('investment-scenario-editor')).toEqual(typed);
    expect((screen.getByRole('button', { name: 'Save Scenario' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('keeps both editors, and every id unique, while another Deal’s own Strategy editor is open too', async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<App />);
    await openFromSidebar(user);
    await openRiskView(user, 'Strategies');
    await user.click(await screen.findByRole('button', { name: 'Add Strategy' }));
    await user.type(screen.getByLabelText('Strategy Name'), 'Portfolio Bid');
    const typed = draftFields('investment-strategy-editor');

    // A standalone Deal, with its own Deal-scoped Strategy editor open.
    await user.click(within(sidebar()).getByRole('button', { name: 'Deal Library' }));
    await screen.findByRole('heading', { name: 'Deal Library' });
    const openFlex = (await screen.findAllByRole('button', { name: 'Open' })).find((button) =>
      (button.closest('tr, li')?.textContent ?? '').includes('Bayside Flex'),
    );
    await user.click(openFlex as HTMLElement);
    await waitFor(() => expect((screen.getByLabelText('Deal Name') as HTMLInputElement).value).toBe('Bayside Flex'));
    await user.click(screen.getByRole('tab', { name: 'Risk' }));
    await user.click(await screen.findByRole('tab', { name: 'Strategies' }));
    await user.click(await screen.findByRole('button', { name: 'Add Strategy' }));
    // The hidden Investment's editor has a Strategy Name too: address the Deal's.
    await user.type(document.getElementById('strategy-editor-name') as HTMLElement, 'Flex Bid');
    expect(listDealStrategies).toHaveBeenCalledWith('deal-d');
    expect(duplicateIds()).toEqual([]);
    expect(danglingReferences()).toEqual([]);
    expect((document.getElementById('strategy-editor-name') as HTMLInputElement).value).toBe('Flex Bid');
    expect((document.getElementById('investment-strategy-editor-name') as HTMLInputElement).value).toBe('Portfolio Bid');

    // Back to the same Investment: nothing to confirm, nothing lost.
    await openFromSidebar(user);
    expect(confirm).not.toHaveBeenCalled();
    expect(draftFields('investment-strategy-editor')).toEqual(typed);
    confirm.mockRestore();
  });

  it('asks before opening another Investment would discard an open draft: Cancel keeps it, Confirm discards it', async () => {
    const user = userEvent.setup();
    const second: VisibleInvestment = {
      ...INVESTMENT,
      id: 'inv-2',
      name: 'Bayside Single',
      transaction_price: 8_000_000,
      units: [{ unit_id: 'deal-d', ordinal: 0, label: null, unit_kind: 'property', acquisition_month: 0, disposition_month: null }],
    };
    vi.mocked(listVisibleInvestments).mockResolvedValue([INVESTMENT, second]);
    vi.mocked(getVisibleInvestment).mockImplementation(async (id) => (id === 'inv-2' ? second : INVESTMENT));
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<App />);
    await openFromSidebar(user);
    await openRiskView(user, 'Scenarios');
    await user.click(await screen.findByRole('button', { name: 'Add Scenario' }));
    await user.type(screen.getByLabelText('Scenario Name'), 'Office Downside');
    const typed = draftFields('investment-scenario-editor');

    const recent = within(sidebar()).getByRole('list', { name: 'Recent Investments' });
    await user.click(within(recent).getByRole('button', { name: /Bayside Single/ }));
    expect(confirm).toHaveBeenCalledWith('You have an unsaved Scenario draft. Leaving will discard it.');
    expect(screen.getByRole('heading', { name: 'Harbor Portfolio', level: 1 })).toBeTruthy();
    expect(draftFields('investment-scenario-editor')).toEqual(typed);

    confirm.mockReturnValue(true);
    await user.click(within(recent).getByRole('button', { name: /Bayside Single/ }));
    expect(await screen.findByRole('heading', { name: 'Bayside Single', level: 1 })).toBeTruthy();
    expect(document.getElementById('investment-scenario-editor')).toBeNull();
    confirm.mockRestore();
  });
});
