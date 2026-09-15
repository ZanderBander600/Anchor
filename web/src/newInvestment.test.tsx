/**
 * Phase 7 Gate P7.6 -- the New Investment builder, against a mocked `api.ts`.
 *
 * The builder never proposes a Transaction Price and never totals the Deals'
 * prices; a Deal that already owns a hidden decision set is promoted (the same
 * Investment, never a second parent); and every backend refusal is shown in
 * its own words with each Deal named.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Mock } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  createVisibleInvestment,
  InvestmentApiError,
  listDealScenarios,
  listDealStrategies,
  promoteHiddenInvestment,
} from './api';
import { NewInvestmentPanel } from './components/NewInvestmentPanel';
import { UNIT_KIND_NOTE } from './investmentCatalog';
import type { VisibleInvestment } from './investmentTypes';
import type { AcquisitionRequest, Deal } from './types';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    createVisibleInvestment: vi.fn(),
    listDealScenarios: vi.fn(),
    listDealStrategies: vi.fn(),
    promoteHiddenInvestment: vi.fn(),
  };
});

const mockCreate = vi.mocked(createVisibleInvestment);
const mockPromote = vi.mocked(promoteHiddenInvestment);
const mockStrategies = vi.mocked(listDealStrategies);
const mockScenarios = vi.mocked(listDealScenarios);

function terms(price: number): AcquisitionRequest {
  return {
    purchase_price: price,
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
}

function deal(id: string, name: string, mode: Deal['operating_mode'], price: number): Deal {
  return {
    id,
    name,
    operating_mode: mode,
    inputs: mode === 'quick' ? terms(price) : null,
    terms: mode === 'quick' ? null : terms(price),
    business_plan: { capital_items: [], owner_expense_items: [] },
    updated_at: `${id}-saved`,
  } as unknown as Deal;
}

const DEALS = [
  deal('deal-a', 'Harbor Retail', 'quick', 12_500_000),
  deal('deal-b', 'Harbor Office', 'detailed', 20_000_000),
  deal('deal-c', 'Harbor Industrial', 'lease_level', 12_500_000),
  deal('deal-x', 'Bayside Flex', 'quick', 8_000_000),
];

const OTHER: VisibleInvestment = {
  id: 'inv-9',
  name: 'Bayside Portfolio',
  transaction_price: 8_000_000,
  units: [{ unit_id: 'deal-x', ordinal: 0, label: null, unit_kind: 'property', acquisition_month: 0, disposition_month: null }],
  business_plan: { capital_items: [], owner_expense_items: [] },
  transaction_costs: [],
  created_at: '2026-09-14T00:00:00+00:00',
  updated_at: '2026-09-14T00:00:00+00:00',
};

const CREATED: VisibleInvestment = { ...OTHER, id: 'inv-new', name: 'Harbor Portfolio', transaction_price: 45_000_000, units: [] };

let onCreated: Mock<(investment: VisibleInvestment) => void>;

function standalone(dealId: string) {
  mockStrategies.mockImplementation(async (id) => ({ deal_id: id, investment_id: null, strategies: [] }));
  mockScenarios.mockImplementation(async (id) => ({ deal_id: id, investment_id: null, scenarios: [] }));
  return dealId;
}

beforeEach(() => {
  onCreated = vi.fn<(investment: VisibleInvestment) => void>();
  standalone('any');
  mockCreate.mockResolvedValue(CREATED);
  mockPromote.mockResolvedValue(CREATED);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderBuilder() {
  return render(<NewInvestmentPanel deals={DEALS} investments={[OTHER]} onCreated={onCreated} onCancel={vi.fn()} />);
}

function row(name: string): HTMLElement {
  return screen.getByRole('rowheader', { name: new RegExp(`^${name}`) }).closest('tr') as HTMLElement;
}

async function fill(user: ReturnType<typeof userEvent.setup>, price: string) {
  await user.type(screen.getByLabelText('Investment Name'), 'Harbor Portfolio');
  await user.type(screen.getByLabelText('Transaction Price'), price);
}

describe('the New Investment builder', () => {
  it('never proposes or totals a Transaction Price; each Deal shows only its own', async () => {
    const user = userEvent.setup();
    renderBuilder();
    await user.click(screen.getByRole('checkbox', { name: 'Include Harbor Retail' }));
    await user.click(screen.getByRole('checkbox', { name: 'Include Harbor Office' }));
    expect((screen.getByLabelText('Transaction Price') as HTMLInputElement).value).toBe('');
    expect(within(row('Harbor Retail')).getByText('$12,500,000')).toBeTruthy();
    expect(within(row('Harbor Office')).getByText('$20,000,000')).toBeTruthy();
    expect(screen.queryByText('$32,500,000')).toBeNull();
    expect(screen.getByText(UNIT_KIND_NOTE)).toBeTruthy();
  });

  it('creates a visible Investment over the chosen Deals, with the labels and kinds chosen', async () => {
    const user = userEvent.setup();
    renderBuilder();
    await fill(user, '45000000');
    await user.click(screen.getByRole('checkbox', { name: 'Include Harbor Retail' }));
    await user.type(screen.getByLabelText('Label for Harbor Retail'), 'Podium');
    await user.selectOptions(screen.getByLabelText('Unit Kind for Harbor Retail'), 'component');
    await user.click(screen.getByRole('checkbox', { name: 'Include Harbor Office' }));
    await user.click(screen.getByRole('checkbox', { name: 'Include Harbor Industrial' }));
    await waitFor(() => expect(within(row('Harbor Industrial')).getByText('Standalone')).toBeTruthy());
    await user.click(screen.getByRole('button', { name: 'Create Investment' }));
    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    expect(mockCreate).toHaveBeenCalledWith({
      name: 'Harbor Portfolio',
      transaction_price: 45_000_000,
      units: [
        { unit_id: 'deal-a', label: 'Podium', unit_kind: 'component' },
        { unit_id: 'deal-b', label: null, unit_kind: 'property' },
        { unit_id: 'deal-c', label: null, unit_kind: 'property' },
      ],
      business_plan: { capital_items: [], owner_expense_items: [] },
      transaction_costs: [],
    });
    expect(mockPromote).not.toHaveBeenCalled();
    expect(onCreated).toHaveBeenCalledWith(CREATED);
  });

  it('promotes a Deal’s hidden decision set: the same Investment, never a second parent', async () => {
    const user = userEvent.setup();
    mockStrategies.mockImplementation(async (id) => ({
      deal_id: id,
      investment_id: id === 'deal-b' ? 'wrapper-b' : null,
      strategies: id === 'deal-b' ? [{ investment_id: 'wrapper-b' } as never] : [],
    }));
    mockScenarios.mockImplementation(async (id) => ({
      deal_id: id,
      investment_id: id === 'deal-b' ? 'wrapper-b' : null,
      scenarios: id === 'deal-b' ? [{} as never, {} as never] : [],
    }));
    renderBuilder();
    await fill(user, '32500000');
    await user.click(screen.getByRole('checkbox', { name: 'Include Harbor Retail' }));
    await user.click(screen.getByRole('checkbox', { name: 'Include Harbor Office' }));
    expect(await within(row('Harbor Office')).findByText(/Has 1 strategy and 2 scenarios: they are kept/)).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Create Investment' }));
    await waitFor(() => expect(mockPromote).toHaveBeenCalledTimes(1));
    expect(mockPromote.mock.calls[0][0]).toBe('wrapper-b');
    expect(mockPromote.mock.calls[0][1].units.map((unit) => unit.unit_id)).toEqual(['deal-a', 'deal-b']);
    expect(mockCreate).not.toHaveBeenCalled();
    expect(mockStrategies).toHaveBeenCalledWith('deal-b');
  });

  it('shows the allocation refusal at the price, each Deal named', async () => {
    const user = userEvent.setup();
    mockCreate.mockRejectedValue(
      new InvestmentApiError('refused', 422, {
        investmentIssues: [
          {
            code: 'allocation_mismatch',
            message: "The Units' allocated purchase prices (deal-a: 12500000, deal-b: 20000000) sum to 32500000, which differs from the transaction price 30000000.",
            unit_id: null,
            field: 'transaction_price',
            source_code: null,
          },
        ],
        variantIssues: [],
        planIssues: [],
        reasons: [],
      }),
    );
    renderBuilder();
    await fill(user, '30000000');
    await user.click(screen.getByRole('checkbox', { name: 'Include Harbor Retail' }));
    await user.click(screen.getByRole('checkbox', { name: 'Include Harbor Office' }));
    await waitFor(() => expect(within(row('Harbor Office')).getByText('Standalone')).toBeTruthy());
    await user.click(screen.getByRole('button', { name: 'Create Investment' }));
    const lead = await screen.findByText(/Unit purchase-price allocations do not reconcile/);
    const issues = lead.closest('ul') as HTMLElement;
    expect(issues.id).toBe('new-investment-price-issues');
    expect(issues.textContent).toContain('Harbor Retail: 12500000, Harbor Office: 20000000');
    expect(issues.textContent).not.toContain('deal-a');
    expect((screen.getByLabelText('Transaction Price') as HTMLInputElement).value).toBe('30,000,000');
  });

  it('says which Deals already belong to an Investment, and shows the backend’s refusal', async () => {
    const user = userEvent.setup();
    mockCreate.mockRejectedValue(
      new InvestmentApiError("Deal 'deal-x' is already a Unit of another Investment.", 409, {
        investmentIssues: [],
        variantIssues: [],
        planIssues: [],
        reasons: ["Deal 'deal-x' is already a Unit of another Investment. A Deal belongs to at most one Investment."],
      }),
    );
    renderBuilder();
    expect(within(row('Bayside Flex')).getByText('Unit of Bayside Portfolio')).toBeTruthy();
    await fill(user, '8000000');
    await user.click(screen.getByRole('checkbox', { name: 'Include Bayside Flex' }));
    await user.click(screen.getByRole('button', { name: 'Create Investment' }));
    expect(
      await screen.findByText("Deal 'Bayside Flex' is already a Unit of another Investment. A Deal belongs to at most one Investment."),
    ).toBeTruthy();
    expect(onCreated).not.toHaveBeenCalled();
  });
});
