/**
 * Phase 7 Gate P7.5 -- the Strategy manager and editor, driven through
 * `RiskDecisionWorkspace` (and `useStrategies`) against a mocked `api.ts`.
 *
 * Every assertion on the wire is the exact Strategy body the P7.4 routes
 * accept: whole domains, the unit the open Deal supplies, values on the wire
 * scale. The error classes stay real, so a refusal reaches the hook as the
 * client raises it.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  ApiError,
  createDealStrategy,
  deleteInvestmentStrategy,
  fetchScenarioTargetCatalog,
  fetchStrategyTargetCatalog,
  getDeal,
  listDealScenarios,
  listDealStrategies,
  StrategyApiError,
  updateInvestmentStrategy,
} from './api';
import { RiskDecisionWorkspace } from './components/RiskDecisionWorkspace';
import type { RiskDecisionWorkspaceProps } from './components/RiskDecisionWorkspace';
import {
  BASE_PREFILL_LOADING_MESSAGE,
  BASE_PREFILL_UNAVAILABLE_MESSAGE,
  SAVE_BEFORE_STRATEGIES_MESSAGE,
  STRATEGY_RESOLVES_TO_BASE_MESSAGE,
} from './strategyCatalog';
import type { InvestmentStrategy, StrategyDraft, StrategyIssue } from './strategyTypes';
import type { AcquisitionRequest, Deal } from './types';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    createDealStrategy: vi.fn(),
    deleteInvestmentStrategy: vi.fn(),
    fetchScenarioTargetCatalog: vi.fn(),
    fetchStrategyTargetCatalog: vi.fn(),
    getDeal: vi.fn(),
    listDealScenarios: vi.fn(),
    listDealStrategies: vi.fn(),
    updateInvestmentStrategy: vi.fn(),
  };
});

const mockList = vi.mocked(listDealStrategies);
const mockCreate = vi.mocked(createDealStrategy);
const mockUpdate = vi.mocked(updateInvestmentStrategy);
const mockDelete = vi.mocked(deleteInvestmentStrategy);
const mockGetDeal = vi.mocked(getDeal);

// =============================================================================
// Fixtures
// =============================================================================

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

const BASE_PLAN = {
  capital_items: [
    { item_id: 'cap-roof', description: 'Roof replacement', category: 'building_systems' as const, month: 6, amount: 400_000 },
  ],
  owner_expense_items: [],
};

const SAVED_DEAL = {
  id: 'deal-1',
  name: '111 Main St',
  operating_mode: 'quick',
  inputs: INPUTS,
  terms: null,
  detailed_operating_inputs: null,
  property_inputs: null,
  operating_inputs: null,
  market_leasing: null,
  suites: null,
  leases: null,
  business_plan: BASE_PLAN,
  deal_context: null,
  analysis_snapshot: null,
  ai_snapshot: null,
  one_way_sensitivity_snapshot: null,
  two_way_sensitivity_snapshot: null,
  created_at: '2026-09-14T00:00:00+00:00',
  updated_at: 'saved-1',
} as unknown as Deal;

const CATALOG = {
  quick: [
    { target: 'exit_cap_rate', units: 'decimal rate (0.0725 is 7.25%)' },
    { target: 'noi_growth', units: 'decimal annual rate (0.03 is 3%)' },
  ],
  detailed: [],
  lease_level: [],
};

function record(id: string, name: string, overlays: StrategyDraft['overlays'], description: string | null = null): InvestmentStrategy {
  return {
    investment_id: 'inv-1',
    strategy: { strategy_id: id, name, description, overlays },
    created_at: '2026-09-14T00:00:00+00:00',
    updated_at: '2026-09-14T00:00:00+00:00',
  };
}

const RECAP = record(
  'st-recap',
  'Recapitalize',
  [
    { unit_id: 'deal-1', domain: 'acquisition', content: { purchase_price: 11_750_000, acquisition_cost_pct: 0.015 } },
    { unit_id: 'deal-1', domain: 'financing', content: { ltv: 0.55, interest_rate: 0.0625, amortization: 25, io_period: 3, financing_fee_pct: 0.0075 } },
    { unit_id: 'deal-1', domain: 'business_plan', content: { capital_items: [], owner_expense_items: [] } },
    { unit_id: 'deal-1', domain: 'operating_outcome', content: { outcomes: [{ target: 'exit_cap_rate', operation: 'set', value: 0.06 }] } },
    { unit_id: 'deal-1', domain: 'disposition', content: { hold_period: 7 } },
  ],
  'Lower leverage, longer hold',
);
const PLAIN = record('st-plain', 'Plain', []);

function listed(strategies: InvestmentStrategy[]) {
  return { deal_id: 'deal-1', investment_id: strategies.length === 0 ? null : 'inv-1', strategies };
}

function refusal(issues: StrategyIssue[]): StrategyApiError {
  return new StrategyApiError(issues.map((i) => i.message).join(' '), 422, {
    issues: [],
    strategyIssues: issues,
    planIssues: [],
    reasons: issues.map((i) => i.message),
  });
}

// =============================================================================
// Driving the workspace
// =============================================================================

const DEFAULT_PROPS: RiskDecisionWorkspaceProps = {
  operatingMode: 'quick',
  dealId: 'deal-1',
  isDirty: false,
  savedAt: 'saved-1',
  isActive: true,
  view: 'strategies',
};

function renderStrategies(props: Partial<RiskDecisionWorkspaceProps> = {}) {
  let current = { ...DEFAULT_PROPS, ...props };
  const view = render(<RiskDecisionWorkspace {...current} />);
  return {
    user: userEvent.setup(),
    rerenderWith(next: Partial<RiskDecisionWorkspaceProps>) {
      current = { ...current, ...next };
      view.rerender(<RiskDecisionWorkspace {...current} />);
    },
  };
}

function button(name: string | RegExp): HTMLButtonElement {
  return screen.getByRole('button', { name }) as HTMLButtonElement;
}

async function readyToEdit() {
  await waitFor(() => expect(button('Add Strategy').disabled).toBe(false));
}

function domain(name: string): HTMLElement {
  return screen.getByRole('group', { name });
}

async function choose(user: ReturnType<typeof userEvent.setup>, domainName: string, option: string) {
  await user.click(within(domain(domainName)).getByRole('radio', { name: option }));
}

function field(label: string): HTMLInputElement {
  return screen.getByLabelText(label) as HTMLInputElement;
}

async function retype(user: ReturnType<typeof userEvent.setup>, label: string, text: string) {
  await user.clear(field(label));
  await user.type(field(label), text);
}

beforeEach(() => {
  vi.resetAllMocks();
  mockList.mockResolvedValue(listed([]));
  vi.mocked(listDealScenarios).mockResolvedValue({ deal_id: 'deal-1', investment_id: null, scenarios: [] });
  vi.mocked(fetchScenarioTargetCatalog).mockResolvedValue({ quick: [], detailed: [], lease_level: [] });
  vi.mocked(fetchStrategyTargetCatalog).mockResolvedValue(CATALOG);
  mockGetDeal.mockResolvedValue(SAVED_DEAL);
});

afterEach(() => {
  cleanup();
});

// =============================================================================
// The manager
// =============================================================================

describe('the Strategy manager', () => {
  it('asks for a save first on an unsaved deal, and requests nothing', async () => {
    renderStrategies({ dealId: null, savedAt: null });
    expect(screen.getByText('Save this deal before adding strategies.')).toBeTruthy();
    expect(button('Add Strategy').disabled).toBe(true);
    await Promise.resolve();
    expect(mockList).not.toHaveBeenCalled();
    expect(mockCreate).not.toHaveBeenCalled();
  });

  it('shows the implicit, locked Base Strategy first and Add Strategy on a saved deal', async () => {
    renderStrategies();
    await readyToEdit();
    const [base] = within(screen.getByRole('list', { name: 'Strategies' })).getAllByRole('listitem');
    expect(within(base).getByText('Base Strategy')).toBeTruthy();
    expect(within(base).getByText('Locked')).toBeTruthy();
    expect(within(base).queryByRole('button')).toBeNull();
    expect(mockList).toHaveBeenCalledWith('deal-1');
    expect(screen.queryByText(/Investment/)).toBeNull();
  });

  it('lists saved Strategies with the domains each replaces, in the analyst’s words', async () => {
    mockList.mockResolvedValue(listed([RECAP, PLAIN]));
    renderStrategies();
    await readyToEdit();
    const items = within(screen.getByRole('list', { name: 'Strategies' })).getAllByRole('listitem');
    const recap = items.find((item) => within(item).queryByText('Recapitalize') !== null) as HTMLElement;
    expect(within(recap).getByText('Lower leverage, longer hold')).toBeTruthy();
    expect(within(recap).getByText('Replaces: Acquisition · Financing · Business Plan · Operating Outcome · Disposition')).toBeTruthy();
    expect(within(recap).getByText('$11,750,000 · 1.50% acquisition costs')).toBeTruthy();
    expect(within(recap).getByText('55.00% LTV · 6.25% rate · 25-yr amortization · 3-yr interest-only · 0.75% fee')).toBeTruthy();
    expect(within(recap).getByText('No Business Plan')).toBeTruthy();
    expect(within(recap).getByText('Exit Cap Rate 6%')).toBeTruthy();
    expect(within(recap).getByText('7-year hold')).toBeTruthy();
    const plain = items.find((item) => within(item).queryByText('Plain') !== null) as HTMLElement;
    expect(within(plain).getByText('Inherits Base')).toBeTruthy();
    expect(within(plain).getByText(STRATEGY_RESOLVES_TO_BASE_MESSAGE)).toBeTruthy();
    const text = document.body.textContent ?? '';
    for (const hidden of ['deal-1', 'inv-1', 'st-recap', 'operating_outcome', 'exit_cap_rate']) {
      expect(text).not.toContain(hidden);
    }
  });

  it('deletes only after an inline confirmation, and Cancel deletes nothing', async () => {
    mockList.mockResolvedValue(listed([RECAP]));
    mockDelete.mockResolvedValue(undefined);
    const { user } = renderStrategies();
    await readyToEdit();

    await user.click(button('Delete Recapitalize'));
    const confirm = screen.getByRole('group', { name: 'Confirm deleting Recapitalize' });
    expect(document.activeElement).toBe(within(confirm).getByRole('button', { name: 'Cancel' }));
    await user.click(within(confirm).getByRole('button', { name: 'Cancel' }));
    expect(mockDelete).not.toHaveBeenCalled();

    await user.click(button('Delete Recapitalize'));
    await user.click(button('Delete Strategy'));
    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith('inv-1', 'st-recap'));
    await waitFor(() => expect(screen.queryByText('Recapitalize')).toBeNull());
  });

  it('keeps the Strategy and the confirmation when a delete fails', async () => {
    mockList.mockResolvedValue(listed([RECAP]));
    mockDelete.mockRejectedValueOnce(new ApiError('Could not reach the Anchor API.'));
    const { user } = renderStrategies();
    await readyToEdit();
    await user.click(button('Delete Recapitalize'));
    await user.click(button('Delete Strategy'));
    expect((await screen.findByRole('alert')).textContent).toBe('Could not reach the Anchor API.');
    expect(screen.getByText('Recapitalize')).toBeTruthy();
  });
});

// =============================================================================
// The editor
// =============================================================================

describe('the Strategy editor', () => {
  it('prefills each domain from the saved Base when first enabled, and sends whole domains on the wire scale', async () => {
    mockCreate.mockResolvedValue(record('st-new', 'Value-Add', []));
    const { user } = renderStrategies();
    await readyToEdit();
    await user.click(button('Add Strategy'));
    expect(document.activeElement).toBe(field('Strategy Name'));
    await waitFor(() => expect(mockGetDeal).toHaveBeenCalledWith('deal-1'));
    await waitFor(() => expect(within(domain('Acquisition')).getByText('$12,500,000 · 2.00% acquisition costs')).toBeTruthy());

    await user.type(field('Strategy Name'), 'Value-Add');
    await choose(user, 'Acquisition', 'Strategy-specific');
    expect(field('Purchase Price').value).toBe('12,500,000');
    expect(field('Acquisition Costs').value).toBe('2');
    await choose(user, 'Financing', 'Strategy-specific');
    expect(['LTV', 'Interest Rate', 'Amortization', 'Interest-Only Period', 'Financing Fee'].map((l) => field(l).value)).toEqual([
      '65', '5.75', '30', '2', '1',
    ]);
    await retype(user, 'LTV', '60');
    await choose(user, 'Disposition', 'Strategy-specific');
    expect(field('Hold Period').value).toBe('5');
    await retype(user, 'Hold Period', '7');
    await user.click(button('Save Strategy'));

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    expect(mockCreate).toHaveBeenCalledWith('deal-1', {
      name: 'Value-Add',
      description: null,
      overlays: [
        { unit_id: 'deal-1', domain: 'acquisition', content: { purchase_price: 12_500_000, acquisition_cost_pct: 0.02 } },
        { unit_id: 'deal-1', domain: 'financing', content: { ltv: 0.6, interest_rate: 0.0575, amortization: 30, io_period: 2, financing_fee_pct: 0.01 } },
        { unit_id: 'deal-1', domain: 'disposition', content: { hold_period: 7 } },
      ],
    });
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'New Strategy' })).toBeNull());
    expect(document.activeElement).toBe(button('Add Strategy'));
  });

  it('offers operating outcomes without an operation, sends SET, and never offers a target twice', async () => {
    mockCreate.mockResolvedValue(record('st-new', 'Repositioned', []));
    const { user } = renderStrategies();
    await readyToEdit();
    await user.click(button('Add Strategy'));
    await user.type(field('Strategy Name'), 'Repositioned');
    await choose(user, 'Operating Outcome', 'Strategy-specific');

    const outcome = domain('Operating Outcome');
    expect(within(outcome).queryByLabelText(/Operation/)).toBeNull();
    const [first] = within(outcome).getAllByLabelText('Assumption') as HTMLSelectElement[];
    await user.selectOptions(first, 'exit_cap_rate');
    await user.type(field('Value for Exit Cap Rate'), '5.75');
    await user.click(within(outcome).getByRole('button', { name: 'Add Assumption' }));
    const second = within(outcome).getAllByLabelText('Assumption')[1] as HTMLSelectElement;
    expect(Array.from(second.options).map((o) => o.textContent)).toEqual(['Choose assumption…', 'NOI Growth']);
    await user.selectOptions(second, 'noi_growth');
    await user.type(field('Value for NOI Growth'), '4');
    expect((within(outcome).getByRole('button', { name: 'Add Assumption' }) as HTMLButtonElement).disabled).toBe(true);
    await user.click(button('Save Strategy'));

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    expect(mockCreate.mock.calls[0][1].overlays).toEqual([
      {
        unit_id: 'deal-1',
        domain: 'operating_outcome',
        content: {
          outcomes: [
            { target: 'exit_cap_rate', operation: 'set', value: 0.0575 },
            { target: 'noi_growth', operation: 'set', value: 0.04 },
          ],
        },
      },
    ]);
  });

  it('keeps Inherit Base, No Business Plan and Custom as three distinct choices', async () => {
    mockCreate.mockResolvedValue(record('st-new', 'x', []));
    const { user } = renderStrategies();
    await readyToEdit();
    await user.click(button('Add Strategy'));
    await waitFor(() => expect(within(domain('Business Plan')).getByText(/Custom Business Plan · 1 capital item/)).toBeTruthy());
    await user.type(field('Strategy Name'), 'No Capital');

    // Inherit Base: no overlay at all.
    expect((within(domain('Business Plan')).getByRole('radio', { name: 'Inherit Base' }) as HTMLInputElement).checked).toBe(true);
    // No Business Plan: an explicit empty plan.
    await choose(user, 'Business Plan', 'No Business Plan');
    expect(within(domain('Business Plan')).getByText(/executes no Business Plan/)).toBeTruthy();
    await user.click(button('Save Strategy'));
    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    expect(mockCreate.mock.calls[0][1].overlays).toEqual([
      { unit_id: 'deal-1', domain: 'business_plan', content: { capital_items: [], owner_expense_items: [] } },
    ]);
  });

  it('starts a Custom plan as a copy of Base, edits it in the one Business Plan editor, and sends the whole plan', async () => {
    mockCreate.mockResolvedValue(record('st-new', 'Renovate', []));
    const { user } = renderStrategies();
    await readyToEdit();
    await user.click(button('Add Strategy'));
    await waitFor(() => expect(mockGetDeal).toHaveBeenCalled());
    await waitFor(() => expect(within(domain('Business Plan')).getByText(/· 1 capital item/)).toBeTruthy());
    await user.type(field('Strategy Name'), 'Renovate');
    await choose(user, 'Business Plan', 'Custom Business Plan');

    const plan = within(domain('Business Plan'));
    expect(plan.getByText(/A complete replacement plan/)).toBeTruthy();
    expect((plan.getByLabelText('Description, Roof replacement') as HTMLInputElement).value).toBe('Roof replacement');
    // Its own ids: never the Deal plan's.
    expect(document.getElementById('business-plan-add-capital')).toBeNull();
    expect(document.getElementById('strategy-business-plan-add-capital')).not.toBeNull();
    await user.clear(plan.getByLabelText('Amount, Roof replacement'));
    await user.type(plan.getByLabelText('Amount, Roof replacement'), '650000');
    await user.click(button('Save Strategy'));

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    expect(mockCreate.mock.calls[0][1].overlays).toEqual([
      {
        unit_id: 'deal-1',
        domain: 'business_plan',
        content: {
          capital_items: [{ item_id: 'cap-roof', description: 'Roof replacement', category: 'building_systems', month: 6, amount: 650_000 }],
          owner_expense_items: [],
        },
      },
    ]);
  });

  it('reopens a saved Strategy with every domain as stated, in display units', async () => {
    mockList.mockResolvedValue(listed([RECAP]));
    const { user } = renderStrategies();
    await readyToEdit();
    await user.click(button('Edit Recapitalize'));

    expect(screen.getByRole('heading', { name: 'Edit Strategy' })).toBeTruthy();
    expect(field('Strategy Name').value).toBe('Recapitalize');
    expect(field('Description (optional)').value).toBe('Lower leverage, longer hold');
    expect(field('Purchase Price').value).toBe('11,750,000');
    expect(field('Acquisition Costs').value).toBe('1.5');
    expect(['LTV', 'Interest Rate', 'Amortization', 'Interest-Only Period', 'Financing Fee'].map((l) => field(l).value)).toEqual([
      '55', '6.25', '25', '3', '0.75',
    ]);
    expect((within(domain('Business Plan')).getByRole('radio', { name: 'No Business Plan' }) as HTMLInputElement).checked).toBe(true);
    expect(field('Value for Exit Cap Rate').value).toBe('6');
    expect(field('Hold Period').value).toBe('7');
  });

  it('allows a Strategy with no economic domain, saying it resolves to Base', async () => {
    mockCreate.mockResolvedValue(record('st-new', 'Same as Base', []));
    const { user } = renderStrategies();
    await readyToEdit();
    await user.click(button('Add Strategy'));
    expect(screen.getByText(STRATEGY_RESOLVES_TO_BASE_MESSAGE)).toBeTruthy();
    await user.type(field('Strategy Name'), 'Same as Base');
    await user.click(button('Save Strategy'));
    await waitFor(() => expect(mockCreate).toHaveBeenCalledWith('deal-1', { name: 'Same as Base', description: null, overlays: [] }));
  });

  it('refuses a partly stated domain before sending, in that domain', async () => {
    const { user } = renderStrategies();
    await readyToEdit();
    await user.click(button('Add Strategy'));
    await waitFor(() => expect(within(domain('Acquisition')).getByText('$12,500,000 · 2.00% acquisition costs')).toBeTruthy());
    await user.type(field('Strategy Name'), 'Bid');
    await choose(user, 'Acquisition', 'Strategy-specific');
    await user.clear(field('Purchase Price'));
    await user.click(button('Save Strategy'));

    expect(within(domain('Acquisition')).getByText('Purchase Price is required.')).toBeTruthy();
    expect(mockCreate).not.toHaveBeenCalled();
  });

  it('shows a backend refusal on the domain and row it names, and keeps every value', async () => {
    mockList.mockResolvedValue(listed([RECAP]));
    mockUpdate.mockRejectedValueOnce(
      refusal([
        { stage: 'resolved_inputs', code: 'resolved_input_invalid', message: 'ltv must be at most 0.95.', domain: 'financing', unit_id: 'deal-1', field: 'ltv', target: null, source_code: 'out_of_range' },
        { stage: 'strategy', code: 'invalid_number', message: 'exit_cap_rate must be positive.', domain: 'operating_outcome', unit_id: 'deal-1', field: null, target: 'exit_cap_rate', source_code: null },
      ]),
    );
    const { user } = renderStrategies();
    await readyToEdit();
    await user.click(button('Edit Recapitalize'));
    await retype(user, 'LTV', '99');
    await user.click(button('Save Strategy'));

    expect(await within(domain('Financing')).findByText('ltv must be at most 0.95.')).toBeTruthy();
    expect(within(domain('Operating Outcome')).getByText('exit_cap_rate must be positive.')).toBeTruthy();
    expect(screen.getByText('The strategy was not saved. The backend refused it for these reasons:')).toBeTruthy();
    expect(field('LTV').value).toBe('99');
    expect(mockUpdate).toHaveBeenCalledWith('inv-1', 'st-recap', expect.objectContaining({ name: 'Recapitalize' }));
  });

  it('keeps the draft after a failed request and saves on a retry', async () => {
    mockCreate.mockRejectedValueOnce(new ApiError('Could not reach the Anchor API.'));
    mockCreate.mockResolvedValueOnce(record('st-new', 'Retry', []));
    const { user } = renderStrategies();
    await readyToEdit();
    await user.click(button('Add Strategy'));
    await user.type(field('Strategy Name'), 'Retry');
    await user.click(button('Save Strategy'));
    expect(await screen.findByText('Could not reach the Anchor API.')).toBeTruthy();
    expect(field('Strategy Name').value).toBe('Retry');
    await user.click(button('Save Strategy'));
    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'New Strategy' })).toBeNull());
  });
});

// =============================================================================
// The saved Base arrives before a domain is prefilled
// =============================================================================

describe('the saved Base arrives before a domain is prefilled', () => {
  function specific(domainName: string): HTMLInputElement {
    return within(domain(domainName)).getByRole('radio', { name: 'Strategy-specific' }) as HTMLInputElement;
  }

  function planOption(name: string): HTMLInputElement {
    return within(domain('Business Plan')).getByRole('radio', { name }) as HTMLInputElement;
  }

  it('holds every Base-dependent first enable until the saved Base is read, then prefills each domain whole', async () => {
    let release: (deal: Deal) => void = () => undefined;
    mockGetDeal.mockImplementation(
      () =>
        new Promise<Deal>((resolve) => {
          release = resolve;
        }),
    );
    const { user } = renderStrategies();
    await readyToEdit();
    await user.click(button('Add Strategy'));
    await waitFor(() => expect(mockGetDeal).toHaveBeenCalledWith('deal-1'));

    // 1-3. The Base is still in flight: no Base-dependent transition can happen.
    expect(screen.getByText(BASE_PREFILL_LOADING_MESSAGE)).toBeTruthy();
    for (const name of ['Acquisition', 'Financing', 'Disposition']) {
      expect(specific(name).disabled, name).toBe(true);
    }
    expect(planOption('Custom Business Plan').disabled).toBe(true);
    // Choices that copy nothing from Base stay open.
    expect(specific('Operating Outcome').disabled).toBe(false);
    expect(planOption('No Business Plan').disabled).toBe(false);
    // The race the analyst could lose before: nothing becomes strategy-specific and blank.
    await user.click(specific('Acquisition'));
    expect(specific('Acquisition').checked).toBe(false);
    expect(screen.queryByLabelText('Purchase Price')).toBeNull();

    // 4. The Base arrives.
    release(SAVED_DEAL);
    await waitFor(() => expect(specific('Acquisition').disabled).toBe(false));
    expect(screen.queryByText(BASE_PREFILL_LOADING_MESSAGE)).toBeNull();

    // 5-6. Each domain's first enable copies the whole domain from Base.
    await choose(user, 'Acquisition', 'Strategy-specific');
    expect([field('Purchase Price').value, field('Acquisition Costs').value]).toEqual(['12,500,000', '2']);
    await choose(user, 'Financing', 'Strategy-specific');
    expect(['LTV', 'Interest Rate', 'Amortization', 'Interest-Only Period', 'Financing Fee'].map((l) => field(l).value)).toEqual([
      '65', '5.75', '30', '2', '1',
    ]);
    await choose(user, 'Disposition', 'Strategy-specific');
    expect(field('Hold Period').value).toBe('5');
    await choose(user, 'Business Plan', 'Custom Business Plan');
    expect((within(domain('Business Plan')).getByLabelText('Description, Roof replacement') as HTMLInputElement).value).toBe(
      'Roof replacement',
    );
  });

  it('keeps a reopened Strategy’s explicit domains editable while the Base is still loading', async () => {
    mockList.mockResolvedValue(listed([RECAP]));
    mockGetDeal.mockImplementation(() => new Promise<Deal>(() => undefined));
    const { user } = renderStrategies();
    await readyToEdit();
    await user.click(button('Edit Recapitalize'));

    expect(screen.getByText(BASE_PREFILL_LOADING_MESSAGE)).toBeTruthy();
    expect(field('Purchase Price').disabled).toBe(false);
    await retype(user, 'Purchase Price', '11500000');
    // Explicit values need no Base: back to Inherit and out again keeps them.
    await choose(user, 'Acquisition', 'Inherit Base');
    expect(specific('Acquisition').disabled).toBe(false);
    await choose(user, 'Acquisition', 'Strategy-specific');
    expect(field('Purchase Price').value).toBe('11,500,000');
    expect(specific('Financing').disabled).toBe(false);
    expect(planOption('Custom Business Plan').disabled).toBe(false);
  });

  it('says when the Base could not be read, prefills nothing, and retries', async () => {
    mockGetDeal.mockRejectedValueOnce(new ApiError('Could not reach the Anchor API.'));
    const { user } = renderStrategies();
    await readyToEdit();
    await user.click(button('Add Strategy'));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain(BASE_PREFILL_UNAVAILABLE_MESSAGE);
    expect(specific('Acquisition').disabled).toBe(true);
    expect(planOption('Custom Business Plan').disabled).toBe(true);

    await user.click(within(alert).getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(specific('Acquisition').disabled).toBe(false));
    expect(mockGetDeal).toHaveBeenCalledTimes(2);
    await choose(user, 'Acquisition', 'Strategy-specific');
    expect([field('Purchase Price').value, field('Acquisition Costs').value]).toEqual(['12,500,000', '2']);
  });
});

// =============================================================================
// A dirty base locks an editor that is already open
// =============================================================================

describe('a dirty base locks an open Strategy editor', () => {
  function controls(): (HTMLInputElement | HTMLSelectElement | HTMLButtonElement)[] {
    const editor = screen.getByRole('heading', { name: /Strategy$/ }).closest('section') as HTMLElement;
    return [
      ...within(editor).getAllByRole('textbox'),
      ...within(editor).getAllByRole('radio'),
      ...within(editor).queryAllByRole('combobox'),
      ...within(editor).getAllByRole('button').filter((b) => b.textContent !== 'Cancel'),
    ] as (HTMLInputElement | HTMLSelectElement | HTMLButtonElement)[];
  }

  it('keeps the draft on screen and locked, Cancel available, and unlocks the same draft when clean', async () => {
    mockList.mockResolvedValue(listed([RECAP]));
    mockUpdate.mockResolvedValue({ ...RECAP, strategy: { ...RECAP.strategy, name: 'Recap revised' } });
    const { user, rerenderWith } = renderStrategies();
    await readyToEdit();
    await user.click(button('Edit Recapitalize'));
    await retype(user, 'Strategy Name', 'Recap revised');
    await retype(user, 'LTV', '50');
    const draft = () => [field('Strategy Name').value, field('LTV').value, field('Hold Period').value];
    expect(draft()).toEqual(['Recap revised', '50', '7']);

    rerenderWith({ isDirty: true });
    expect(screen.getByRole('heading', { name: 'Edit Strategy' })).toBeTruthy();
    // Said in the Strategies view (the matrix view says it too, for Refresh).
    const strategiesPanel = document.getElementById('risk-panel-strategies') as HTMLElement;
    expect(within(strategiesPanel).getByText(SAVE_BEFORE_STRATEGIES_MESSAGE)).toBeTruthy();
    const locked = controls();
    expect(locked.length).toBeGreaterThan(15);
    for (const control of locked) {
      expect(control.disabled, control.id || control.getAttribute('aria-label') || control.textContent).toBe(true);
    }
    expect(button('Save Strategy').disabled).toBe(true);
    expect(button('Cancel').disabled).toBe(false);
    await user.type(field('Strategy Name'), ' again');
    expect(draft()).toEqual(['Recap revised', '50', '7']);
    expect(button('Add Strategy').disabled).toBe(true);
    expect(button('Delete Recapitalize').disabled).toBe(true);

    rerenderWith({ isDirty: false });
    for (const control of controls()) {
      expect(control.disabled, control.id || control.textContent).toBe(false);
    }
    expect(draft()).toEqual(['Recap revised', '50', '7']);
    await user.click(button('Save Strategy'));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));
    expect(mockUpdate.mock.calls[0][2].name).toBe('Recap revised');
  });

  it('lets Cancel leave a locked new draft', async () => {
    const { user, rerenderWith } = renderStrategies();
    await readyToEdit();
    await user.click(button('Add Strategy'));
    await user.type(field('Strategy Name'), 'Draft');
    rerenderWith({ isDirty: true });
    await user.click(button('Cancel'));
    expect(screen.queryByRole('heading', { name: 'New Strategy' })).toBeNull();
    expect(mockCreate).not.toHaveBeenCalled();
  });
});
