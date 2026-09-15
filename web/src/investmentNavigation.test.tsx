/**
 * Phase 7 Gate P7.6 -- Deals and Investments in the one application shell.
 *
 * Driven through `App` against a mocked `api.ts`: the sidebar offers both,
 * each with its own library; a visible Investment opens its own workspace; a
 * Unit opens in its own, existing Deal workspace with a way back that re-reads
 * the Investment; and a Deal that is a Unit points to its Investment rather
 * than calling routes that refuse it.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import {
  createVisibleInvestment,
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
    fetchScenarioTargetCatalog: vi.fn(async () => ({ quick: [], detailed: [], lease_level: [] })),
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

function quickDeal(id: string, name: string, price: number): Deal {
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
    updated_at: `${id}-saved`,
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

beforeEach(() => {
  vi.mocked(listDeals).mockResolvedValue([RETAIL, OFFICE, FLEX]);
  vi.mocked(getDeal).mockImplementation(async (id) => [RETAIL, OFFICE, FLEX].find((deal) => deal.id === id) as Deal);
  vi.mocked(listVisibleInvestments).mockResolvedValue([INVESTMENT]);
  vi.mocked(getVisibleInvestment).mockResolvedValue(INVESTMENT);
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
    // The hidden Investment keeps its drafts but not a second copy of the
    // decision tools: every Risk panel id is the Deal's, and unique.
    for (const id of ['risk-panel-matrix', 'risk-panel-strategies', 'risk-panel-scenarios', 'risk-tab-matrix']) {
      expect(document.querySelectorAll(`#${id}`), id).toHaveLength(1);
    }

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
