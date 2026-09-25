/**
 * Phase 7 Gate P7.6 -- the visible Investment workspace, driven against a
 * mocked `api.ts`.
 *
 * Every consolidated figure asserted here is a field of the backend's
 * `ConsolidatedResults`, formatted. The fixture is deliberately *not*
 * internally consistent -- its totals are not the sums of its parts -- so a UI
 * that added anything up would print a different string and fail.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Mock } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  addInvestmentUnit,
  analyzeInvestmentVariant,
  deleteVisibleInvestment,
  fetchScenarioTargetCatalog,
  fetchStrategyTargetCatalog,
  getDeal,
  getVisibleInvestment,
  InvestmentApiError,
  listDeals,
  listInvestmentScenarios,
  listInvestmentStrategies,
  removeInvestmentUnit,
  updateInvestmentUnitDisplay,
  updateVisibleInvestmentDetails,
  readCapitalEventPresence,
  readInvestmentCapitalStructure,
} from './api';
import { irrNotReportedExplanation } from './capitalEconomics';
import { InvestmentWorkspace } from './components/InvestmentWorkspace';
import {
  DELETE_INVESTMENT_CONSEQUENCES,
  INVESTMENT_ANALYSIS_DIRTY_MESSAGE,
  INVESTMENT_ANALYSIS_STALE_MESSAGE,
  INVESTMENT_BUSINESS_PLAN_NOTE,
  INVESTMENT_DIRTY_MESSAGE,
  LAST_UNIT_MESSAGE,
  REMOVE_UNIT_CONSEQUENCES,
  TRANSACTION_COST_NOTE,
} from './investmentCatalog';
import type { ConsolidatedResults, InvestmentVariantAnalysis, VisibleInvestment } from './investmentTypes';
import type { AcquisitionRequest, Deal } from './types';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    addInvestmentUnit: vi.fn(),
    analyzeInvestmentVariant: vi.fn(),
    deleteVisibleInvestment: vi.fn(),
    fetchScenarioTargetCatalog: vi.fn(),
    fetchStrategyTargetCatalog: vi.fn(),
    getDeal: vi.fn(),
    getVisibleInvestment: vi.fn(),
    listDeals: vi.fn(),
    listInvestmentScenarios: vi.fn(),
    listInvestmentStrategies: vi.fn(),
    readCapitalEventPresence: vi.fn(),
    readInvestmentCapitalStructure: vi.fn(),
    removeInvestmentUnit: vi.fn(),
    updateInvestmentUnitDisplay: vi.fn(),
    updateVisibleInvestmentDetails: vi.fn(),
  };
});

const mockGet = vi.mocked(getVisibleInvestment);
const mockDeals = vi.mocked(listDeals);
const mockAnalyze = vi.mocked(analyzeInvestmentVariant);
const mockDetails = vi.mocked(updateVisibleInvestmentDetails);
const mockDisplay = vi.mocked(updateInvestmentUnitDisplay);
const mockAdd = vi.mocked(addInvestmentUnit);
const mockRemove = vi.mocked(removeInvestmentUnit);
const mockDelete = vi.mocked(deleteVisibleInvestment);

// =============================================================================
// Fixtures
// =============================================================================

function terms(price: number, hold: number): AcquisitionRequest {
  return {
    purchase_price: price,
    current_noi: 800_000,
    occupancy: 0.94,
    noi_growth: 0.03,
    hold_period: hold,
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

function deal(id: string, name: string, mode: Deal['operating_mode'], price: number, savedAt = `${id}-saved`): Deal {
  const inputs = terms(price, 5);
  return {
    id,
    name,
    operating_mode: mode,
    inputs: mode === 'quick' ? inputs : null,
    terms: mode === 'quick' ? null : inputs,
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
    created_at: '2026-09-14T00:00:00+00:00',
    updated_at: savedAt,
  } as unknown as Deal;
}

const RETAIL = deal('deal-a', 'Harbor Retail', 'quick', 12_500_000);
const OFFICE = deal('deal-b', 'Harbor Office', 'detailed', 20_000_000);
const INDUSTRIAL = deal('deal-c', 'Harbor Industrial', 'lease_level', 12_500_000);
const STANDALONE = deal('deal-d', 'Bayside Flex', 'quick', 8_000_000);
const DEALS = [RETAIL, OFFICE, INDUSTRIAL, STANDALONE];

const INVESTMENT: VisibleInvestment = {
  id: 'inv-1',
  name: 'Harbor Portfolio',
  transaction_price: 45_000_000,
  units: [
    { unit_id: 'deal-a', ordinal: 0, label: 'Podium', unit_kind: 'component', acquisition_month: 0, disposition_month: null },
    { unit_id: 'deal-b', ordinal: 1, label: null, unit_kind: 'property', acquisition_month: 0, disposition_month: null },
    { unit_id: 'deal-c', ordinal: 2, label: null, unit_kind: 'property', acquisition_month: 0, disposition_month: null },
  ],
  business_plan: { capital_items: [], owner_expense_items: [] },
  transaction_costs: [
    { cost_id: 'cost-1', description: 'Portfolio legal', category: 'legal', amount: 125_000, model_month: 0 },
  ],
  created_at: '2026-09-14T00:00:00+00:00',
  updated_at: 'inv-saved-1',
};

/** Deliberately not internally consistent: nothing here is the sum of its
 * parts, so any frontend total would print something else. */
const RESULTS: ConsolidatedResults = {
  unit_ids: ['deal-a', 'deal-b', 'deal-c'],
  hold_period: 5,
  transaction_price: 45_000_000,
  allocated_purchase_price: 45_000_000.004,
  allocation_variance: 0.004,
  acquisition_costs: 911_111,
  financing_fees: 292_222,
  investment_transaction_costs: 350_333,
  investment_closing_project_capital: 125_444,
  closing_project_capital: 425_555,
  loan_amount: 29_250_666,
  initial_equity: 17_717_777,
  total_closing_uses: 46_967_888,
  total_closing_sources: 46_967_999,
  unlevered_project_basis: 46_675_000,
  noi_by_year: [2_700_101, 2_781_202, 2_864_303, 2_950_404, 3_038_505],
  capex_by_year: [90_011, 90_012, 90_013, 90_014, 90_015],
  tenant_improvements_by_year: [0, 0, 150_000, 0, 0],
  leasing_commissions_by_year: [0, 0, 45_000, 0, 0],
  property_cash_flow_by_year: [2_610_090, 2_691_190, 2_579_290, 2_860_390, 2_948_490],
  investment_project_capital_by_year: [0, 75_000, 0, 0, 0],
  investment_owner_expenses_by_year: [60_000, 60_000, 60_000, 60_000, 60_000],
  project_capital_by_year: [0, 175_000, 0, 0, 0],
  owner_expenses_by_year: [60_000, 60_000, 60_000, 60_000, 60_000],
  unlevered_owner_cash_flow_by_year: [2_550_090, 2_456_190, 2_519_290, 2_800_390, 2_888_490],
  annual_debt_service: [1_681_909, 1_681_909, 2_048_127, 2_048_127, 2_048_127],
  levered_owner_cash_flow_by_year: [868_181, 774_281, -471_163, 752_263, 840_363],
  remaining_loan_balance: 28_100_000,
  exit_noi: 3_129_660,
  exit_value: 51_140_700,
  disposition_costs: 1_022_814,
  net_sale_proceeds: 50_117_886,
  investment_post_hold_project_capital: 0,
  post_hold_project_capital: 0,
  implied_exit_cap_rate: 0.0612,
  unlevered_cash_flows: [-46_675_000, 2_550_090, 2_456_190, 2_519_290, 2_800_390, 53_006_376],
  levered_cash_flows: [-17_717_777, 868_181, 774_281, -471_163, 752_263, 22_858_249],
  unlevered_irr: 0.0987,
  unlevered_irr_status: 'defined',
  levered_irr: null,
  levered_irr_status: 'multiple_sign_changes',
  total_equity_invested: 18_188_940,
  total_cash_returned: 25_253_137,
  total_profit: 7_064_197,
  equity_multiple: 1.63,
  net_additional_equity_requirement_by_year: [0, 0, 471_163, 0, 0],
  aggregate_dscr_by_year: [1.61, 1.65, 1.21, 1.44, 1.48],
  headline_aggregate_dscr: 1.61,
  min_aggregate_dscr: 1.21,
  going_in_cap_rate: 0.06,
  year_1_debt_yield: 0.0923,
  levered_cash_on_cash_by_year: [0.049, 0.044, -0.027, 0.042, 0.047],
  unlevered_cash_yield_by_year: [0.055, 0.053, 0.054, 0.06, 0.062],
  cumulative_operating_distributions_by_year: [868_181, 1_642_462, 1_171_299, 1_923_562, 2_763_925],
  physical_occupancy_at_year_end: null,
  physical_occupancy_reason: 'unit_without_area_measure',
  physical_occupancy_message: 'Deal deal-a reports no rentable area, so the Investment has no area-weighted occupancy.',
};

const ANALYSIS: InvestmentVariantAnalysis = {
  investment_id: 'inv-1',
  strategy_id: 'base',
  scenario_id: 'base',
  source_fingerprint: 'fp-base',
  cache_status: 'bypassed',
  hold_period: 5,
  unit_results: [],
  consolidated_results: RESULTS,
};

interface Handlers {
  onOpenUnit: Mock<(deal: Deal) => void>;
  onChanged: Mock<() => void>;
  onDeleted: Mock<() => void>;
  onUnsavedChange: Mock<(warning: string | null) => void>;
}

let handlers: Handlers;

function renderWorkspace(signal: object = {}) {
  return render(
    <InvestmentWorkspace
      investmentId="inv-1"
      investments={[INVESTMENT]}
      refreshSignal={signal}
      onOpenUnit={handlers.onOpenUnit}
      onChanged={handlers.onChanged}
      onDeleted={handlers.onDeleted}
      onUnsavedChange={handlers.onUnsavedChange}
    />,
  );
}

beforeEach(() => {
  handlers = {
    onOpenUnit: vi.fn<(deal: Deal) => void>(),
    onChanged: vi.fn<() => void>(),
    onDeleted: vi.fn<() => void>(),
    onUnsavedChange: vi.fn<(warning: string | null) => void>(),
  };
  mockGet.mockResolvedValue(INVESTMENT);
  mockDeals.mockResolvedValue(DEALS);
  vi.mocked(getDeal).mockImplementation(async (id) => DEALS.find((candidate) => candidate.id === id) as Deal);
  mockAnalyze.mockResolvedValue(ANALYSIS);
  vi.mocked(listInvestmentStrategies).mockResolvedValue([]);
  vi.mocked(listInvestmentScenarios).mockResolvedValue([]);
  // Refinance V1 Stage 3: a settled answer that no refinance is configured, so
  // these surfaces keep their accepted presentation.
  vi.mocked(readInvestmentCapitalStructure).mockResolvedValue({
    investment_id: 'inv-1',
    capital_structure: { positions: [] },
  } as never);
  vi.mocked(readCapitalEventPresence).mockResolvedValue({
    investment_id: 'inv-1',
    strategies: [],
    acquisition_financing_metrics: [],
  });
  vi.mocked(fetchStrategyTargetCatalog).mockResolvedValue({ quick: [], detailed: [], lease_level: [] });
  vi.mocked(fetchScenarioTargetCatalog).mockResolvedValue({ quick: [], detailed: [], lease_level: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function panel(name: 'Overview' | 'Units' | 'Risk'): HTMLElement {
  return screen.getByRole('tabpanel', { name });
}

/** One ledger line's value. The annual table has row headers too, so only a
 * ledger's is read. */
function ledgerValue(label: string): string {
  const header = screen
    .getAllByRole('rowheader', { name: label })
    .find((candidate) => candidate.closest('.investment-ledger') !== null);
  if (header === undefined) {
    throw new Error(`No ledger line ${label}`);
  }
  const row = header.closest('tr') as HTMLElement;
  return (row.querySelector('td') as HTMLElement).textContent ?? '';
}

async function runBase(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: 'Run Base Analysis' }));
  await screen.findByRole('table', { name: /Returns/ });
}

// =============================================================================
// The Investment, as an Investment
// =============================================================================

describe('the Investment header and workspaces', () => {
  it('says what an Investment is, with no operating-mode toggle', async () => {
    renderWorkspace();
    expect(await screen.findByRole('heading', { name: 'Harbor Portfolio', level: 1 })).toBeTruthy();
    const header = screen.getByRole('banner');
    expect(within(header).getByText('Investment')).toBeTruthy();
    expect(within(header).getByText('$45,000,000')).toBeTruthy();
    expect(within(header).getByText('3 Units')).toBeTruthy();
    expect(screen.queryByRole('tablist', { name: 'Underwriting Mode' })).toBeNull();
    const tabs = within(screen.getByRole('tablist', { name: 'Investment workspace' })).getAllByRole('tab');
    expect(tabs.map((tab) => tab.textContent)).toEqual(['Overview', 'Units', 'Risk']);
  });

  it('offers only the decision tools on Risk: no Investment sensitivity or break-even', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await user.click(await screen.findByRole('tab', { name: 'Risk' }));
    const views = within(screen.getByRole('tablist', { name: 'Investment risk views' })).getAllByRole('tab');
    // Re-pinned at P7.8B, when Capital Structure joined the decision tools at
    // Investment level, and again at P7.9 Stage 3, when Partnership did.
    // Sensitivity and break-even stay Unit-level, which is what this test is
    // actually about, and are still absent.
    expect(views.map((tab) => tab.textContent)).toEqual([
      'Decision Matrix',
      'Strategies',
      'Scenarios',
      'Capital Structure',
      'Partnership',
    ]);
    await waitFor(() => expect(listInvestmentStrategies).toHaveBeenCalledWith('inv-1'));
  });
});

// =============================================================================
// Base consolidated analysis
// =============================================================================

describe('the Base consolidated analysis', () => {
  it('shows the backend’s consolidated figures, formatted, and derives none', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await runBase(user);
    expect(mockAnalyze).toHaveBeenCalledWith('inv-1', 'base', 'base');
    expect(ledgerValue('Unlevered IRR')).toBe('9.87%');
    expect(ledgerValue('Equity Multiple')).toBe('1.63x');
    expect(ledgerValue('Total Profit')).toBe('$7,064,197');
    expect(ledgerValue('Total Equity Invested')).toBe('$18,188,940');
    expect(ledgerValue('Headline Aggregate DSCR')).toBe('1.61x');
    expect(ledgerValue('Minimum Aggregate DSCR')).toBe('1.21x');
    expect(ledgerValue('Year-1 Debt Yield')).toBe('9.23%');
    expect(ledgerValue('Going-In Cap Rate')).toBe('6.00%');
    expect(ledgerValue('Implied Exit Cap Rate')).toBe('6.12%');
    expect(ledgerValue('Exit Value')).toBe('$51,140,700');
    // Closing: each line is its own backend field, not a sum of others.
    expect(ledgerValue('Transaction Price')).toContain('$45,000,000');
    expect(ledgerValue('Allocated Purchase Price')).toContain('$45,000,000');
    expect(ledgerValue('Investment Transaction Costs')).toBe('$350,333');
    expect(ledgerValue('Total Closing Uses')).toBe('$46,967,888');
    expect(ledgerValue('Total Closing Sources')).toBe('$46,967,999');
    // Annual: the backend's series, year by year.
    const cashFlow = screen.getByRole('region', { name: 'Annual consolidated cash flow' });
    const noi = within(cashFlow).getByRole('rowheader', { name: 'NOI' }).closest('tr') as HTMLElement;
    expect(within(noi).getAllByRole('cell').map((cell) => cell.textContent)).toEqual([
      '$2,700,101',
      '$2,781,202',
      '$2,864,303',
      '$2,950,404',
      '$3,038,505',
    ]);
    const dscr = within(cashFlow).getByRole('rowheader', { name: 'Aggregate DSCR' }).closest('tr') as HTMLElement;
    expect(within(dscr).getAllByRole('cell')[2].textContent).toBe('1.21x');
  });

  it('shows an undefined IRR as N/A with its reason, never 0%', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await runBase(user);
    const levered = ledgerValue('Levered IRR');
    expect(levered.startsWith('N/A')).toBe(true);
    expect(levered).toContain(irrNotReportedExplanation('Levered IRR', 'multiple_sign_changes') ?? 'missing');
    expect(levered).not.toContain('0.00%');
  });

  it('shows Year-End Physical Occupancy as N/A with the backend’s reason, never an average', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await runBase(user);
    // The backend's reason, with the Unit it quotes named rather than its id.
    expect(ledgerValue('Year-End Physical Occupancy')).toContain(
      'Deal Harbor Retail (Podium) reports no rentable area, so the Investment has no area-weighted occupancy.',
    );
    expect(ledgerValue('Year-End Physical Occupancy')).not.toContain('deal-a');
    const cashFlow = screen.getByRole('region', { name: 'Annual consolidated cash flow' });
    const occupancy = within(cashFlow).getByRole('rowheader', { name: 'Year-End Physical Occupancy' }).closest('tr') as HTMLElement;
    expect(occupancy.textContent).toContain('N/A');
    expect(occupancy.textContent).not.toMatch(/\d+\.\d+%/);
  });

  it('is out of date once a Unit’s saved underwriting moves, until it is run again', async () => {
    const user = userEvent.setup();
    const { rerender } = renderWorkspace();
    await runBase(user);
    mockDeals.mockResolvedValue([RETAIL, deal('deal-b', 'Harbor Office', 'detailed', 20_000_000, 'deal-b-saved-2'), INDUSTRIAL, STANDALONE]);
    rerender(
      <InvestmentWorkspace
        investmentId="inv-1"
        investments={[INVESTMENT]}
        refreshSignal={{}}
        onOpenUnit={handlers.onOpenUnit}
        onChanged={handlers.onChanged}
        onDeleted={handlers.onDeleted}
        onUnsavedChange={handlers.onUnsavedChange}
      />,
    );
    expect(await screen.findByText(INVESTMENT_ANALYSIS_STALE_MESSAGE)).toBeTruthy();
    expect(screen.queryByRole('table', { name: /Returns/ })).toBeNull();
    expect(screen.queryByRole('region', { name: 'Annual consolidated cash flow' })).toBeNull();
    expect((screen.getByRole('button', { name: 'Refresh Base Analysis' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('keeps an open Strategy draft through a Unit visit; the re-read Unit makes the analysis stale, never the draft', async () => {
    const user = userEvent.setup();
    const signal = {};
    const { rerender } = renderWorkspace(signal);
    await runBase(user);
    await user.click(screen.getByRole('tab', { name: 'Risk' }));
    await user.click(screen.getByRole('tab', { name: 'Strategies' }));
    await user.click(await screen.findByRole('button', { name: 'Add Strategy' }));
    await user.type(screen.getByLabelText('Strategy Name'), 'Hold Longer');
    const office = screen.getByRole('region', { name: 'Harbor Office' });
    const specific = within(within(office).getByRole('radiogroup', { name: 'Disposition' })).getByRole('radio', {
      name: 'Strategy-specific',
    }) as HTMLInputElement;
    await waitFor(() => expect(specific.disabled).toBe(false));
    await user.click(specific);
    await user.click(within(office).getByLabelText('Hold Period'));
    await user.keyboard('{Control>}a{/Control}7');
    const editor = () => document.getElementById('investment-strategy-editor') as HTMLElement;
    const fields = () =>
      [...editor().querySelectorAll('input')].map((input) =>
        input.type === 'radio' ? [`${input.name}=${input.value}`, String(input.checked)] : [input.id, input.value],
      );
    const typed = fields();
    expect(typed).toContainEqual(['investment-strategy-u1-disposition-holdPeriod', '7']);

    const workspace = (isShown: boolean, refreshSignal: object) => (
      <InvestmentWorkspace
        investmentId="inv-1"
        investments={[INVESTMENT]}
        refreshSignal={refreshSignal}
        onOpenUnit={handlers.onOpenUnit}
        onChanged={handlers.onChanged}
        onDeleted={handlers.onDeleted}
        onUnsavedChange={handlers.onUnsavedChange}
        isShown={isShown}
      />
    );
    // Harbor Office's underwriting is open: the Investment is hidden, mounted.
    rerender(workspace(false, signal));
    expect(editor()).toBeTruthy();
    // Harbor Office is saved at a new price; coming back re-reads it.
    const resaved = deal('deal-b', 'Harbor Office', 'detailed', 21_000_000, 'deal-b-saved-2');
    const reread = [RETAIL, resaved, INDUSTRIAL, STANDALONE];
    mockDeals.mockResolvedValue(reread);
    vi.mocked(getDeal).mockImplementation(async (id) => reread.find((candidate) => candidate.id === id) as Deal);
    rerender(workspace(true, {}));

    expect(await screen.findByText(INVESTMENT_ANALYSIS_STALE_MESSAGE)).toBeTruthy();
    expect(mockGet).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(getDeal).toHaveBeenLastCalledWith('deal-b'));
    expect(await within(screen.getByRole('region', { name: 'Harbor Office' })).findByText(/\$21,000,000/)).toBeTruthy();
    expect(fields()).toEqual(typed);
    expect((screen.getByRole('button', { name: 'Save Strategy' }) as HTMLButtonElement).disabled).toBe(false);

    await user.click(screen.getByRole('tab', { name: 'Overview' }));
    expect(screen.queryByRole('table', { name: /Returns/ })).toBeNull();
    await user.click(screen.getByRole('tab', { name: 'Risk' }));
    expect(fields()).toEqual(typed);
  });

  it('stays current when only a Unit’s label, kind or order changes', async () => {
    const user = userEvent.setup();
    mockDisplay.mockResolvedValue({
      ...INVESTMENT,
      units: INVESTMENT.units.map((unit) => (unit.unit_id === 'deal-b' ? { ...unit, label: 'Tower', unit_kind: 'phase', ordinal: 7 } : unit)),
      updated_at: 'inv-saved-2',
    });
    renderWorkspace();
    await runBase(user);
    await user.click(screen.getByRole('tab', { name: 'Units' }));
    await user.click(screen.getByRole('button', { name: 'Edit label, kind and order of Harbor Office' }));
    await user.type(screen.getByLabelText('Label (optional)'), 'Tower');
    await user.selectOptions(screen.getByLabelText('Unit Kind'), 'phase');
    await user.click(screen.getByRole('button', { name: 'Save Unit' }));
    await waitFor(() => expect(mockDisplay).toHaveBeenCalledWith('inv-1', 'deal-b', { label: 'Tower', unit_kind: 'phase', ordinal: 1 }));
    await user.click(screen.getByRole('tab', { name: 'Overview' }));
    expect(screen.getByRole('table', { name: /Returns/ })).toBeTruthy();
    expect(screen.queryByText(INVESTMENT_ANALYSIS_STALE_MESSAGE)).toBeNull();
  });
});

// =============================================================================
// Investment details: one draft, one Save
// =============================================================================

describe('Edit Investment', () => {
  it('keeps one draft with visible dirty state; an economic edit blocks analysis, a rename does not', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await user.click(await screen.findByRole('button', { name: 'Edit Investment' }));
    expect(screen.getByText('No changes yet')).toBeTruthy();

    await user.type(screen.getByLabelText('Investment Name'), ' II');
    expect(screen.getAllByText('Unsaved changes').length).toBeGreaterThan(0);
    expect((screen.getByRole('button', { name: 'Run Base Analysis' }) as HTMLButtonElement).disabled).toBe(false);

    const price = screen.getByLabelText('Transaction Price');
    await user.click(price);
    await user.keyboard('{Control>}a{/Control}45500000');
    expect((screen.getByRole('button', { name: 'Run Base Analysis' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(INVESTMENT_ANALYSIS_DIRTY_MESSAGE)).toBeTruthy();
    expect(handlers.onUnsavedChange).toHaveBeenLastCalledWith(
      'You have unsaved Investment changes. Leaving will discard them.',
    );

    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect((screen.getByLabelText('Transaction Price') as HTMLInputElement).value).toBe('45,000,000');
    expect((screen.getByLabelText('Investment Name') as HTMLInputElement).value).toBe('Harbor Portfolio');
    expect((screen.getByLabelText('Transaction Price') as HTMLInputElement).disabled).toBe(true);
  });

  it('saves the four details together, each cost timed at Closing', async () => {
    const user = userEvent.setup();
    mockDetails.mockImplementation(async (_id, request) => ({ ...INVESTMENT, ...request, updated_at: 'inv-saved-2' }));
    renderWorkspace();
    await user.click(await screen.findByRole('button', { name: 'Edit Investment' }));
    expect(screen.getByText(TRANSACTION_COST_NOTE)).toBeTruthy();
    expect(screen.getByText(INVESTMENT_BUSINESS_PLAN_NOTE)).toBeTruthy();
    const price = screen.getByLabelText('Transaction Price');
    await user.click(price);
    await user.keyboard('{Control>}a{/Control}45500000');
    await user.click(screen.getByRole('button', { name: 'Add Transaction Cost' }));
    await user.type(screen.getAllByLabelText('Description')[1], 'Due diligence');
    await user.selectOptions(screen.getAllByLabelText('Category')[1], 'due_diligence');
    await user.type(screen.getAllByLabelText('Amount')[1], '80000');
    expect(screen.getAllByText('Closing')).toHaveLength(2);
    expect(screen.queryByLabelText('Timing')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Save Investment' }));
    await waitFor(() => expect(mockDetails).toHaveBeenCalledTimes(1));
    const [id, request] = mockDetails.mock.calls[0];
    expect(id).toBe('inv-1');
    expect(request.name).toBe('Harbor Portfolio');
    expect(request.transaction_price).toBe(45_500_000);
    expect(request.business_plan).toEqual({ capital_items: [], owner_expense_items: [] });
    expect(request.transaction_costs).toHaveLength(2);
    expect(request.transaction_costs[0]).toEqual(INVESTMENT.transaction_costs[0]);
    expect(request.transaction_costs[1]).toMatchObject({
      description: 'Due diligence',
      category: 'due_diligence',
      amount: 80_000,
      model_month: 0,
    });
    expect(typeof request.transaction_costs[1].cost_id).toBe('string');
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Save Investment' })).toBeNull());
    expect(handlers.onChanged).toHaveBeenCalled();
  });

  it('shows an allocation refusal at the price, Units named, and keeps the draft', async () => {
    const user = userEvent.setup();
    mockDetails.mockRejectedValue(
      new InvestmentApiError('refused', 422, {
        investmentIssues: [
          {
            code: 'allocation_mismatch',
            message:
              "The Units' allocated purchase prices (deal-a: 12500000, deal-b: 20000000, deal-c: 12500000) sum to 45000000, which differs from the transaction price 44000000 by 1000000.",
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
    renderWorkspace();
    await user.click(await screen.findByRole('button', { name: 'Edit Investment' }));
    const price = screen.getByLabelText('Transaction Price');
    await user.click(price);
    await user.keyboard('{Control>}a{/Control}44000000');
    await user.click(screen.getByRole('button', { name: 'Save Investment' }));
    const refusal = await screen.findByText(/Unit purchase-price allocations do not reconcile to the Investment transaction price\./);
    const list = refusal.closest('ul') as HTMLElement;
    expect(list.textContent).toContain('Harbor Retail (Podium): 12500000, Harbor Office: 20000000, Harbor Industrial: 12500000');
    expect(list.textContent).not.toContain('deal-a');
    expect((screen.getByLabelText('Transaction Price') as HTMLInputElement).value).toBe('44,000,000');
    expect(screen.getByRole('button', { name: 'Save Investment' })).toBeTruthy();
  });

  it('locks Strategy and Scenario changes while economic edits are unsaved', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await user.click(await screen.findByRole('button', { name: 'Edit Investment' }));
    const price = screen.getByLabelText('Transaction Price');
    await user.click(price);
    await user.keyboard('{Control>}a{/Control}45100000');
    await user.click(screen.getByRole('tab', { name: 'Risk' }));
    await user.click(within(panel('Risk')).getByRole('tab', { name: 'Strategies' }));
    const add = await within(panel('Risk')).findByRole('button', { name: 'Add Strategy' });
    await waitFor(() => expect(within(panel('Risk')).getAllByText(INVESTMENT_DIRTY_MESSAGE).length).toBeGreaterThan(0));
    expect((add as HTMLButtonElement).disabled).toBe(true);
  });
});

// =============================================================================
// Units
// =============================================================================

describe('the Units workspace', () => {
  it('shows every member Deal with its mode, kind, stored price and hold, and opens its underwriting', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await user.click(await screen.findByRole('tab', { name: 'Units' }));
    const table = within(panel('Units')).getByRole('table');
    const retail = within(table).getByRole('rowheader', { name: /Harbor Retail/ }).closest('tr') as HTMLElement;
    expect(within(retail).getByText('Podium')).toBeTruthy();
    expect(within(retail).getByText('Component')).toBeTruthy();
    expect(within(retail).getByText('$12,500,000')).toBeTruthy();
    expect(within(retail).getByText('5 yrs')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Open underwriting for Harbor Office' }));
    expect(handlers.onOpenUnit).toHaveBeenCalledWith(OFFICE);
  });

  it('adds a Unit with the analyst’s stated resulting price and never adds one up', async () => {
    const user = userEvent.setup();
    mockAdd
      .mockRejectedValueOnce(
        new InvestmentApiError('refused', 422, {
          investmentIssues: [
            { code: 'allocation_mismatch', message: 'The prices (deal-d: 8000000) do not reconcile.', unit_id: null, field: 'transaction_price', source_code: null },
          ],
          variantIssues: [],
          planIssues: [],
          reasons: [],
        }),
      )
      .mockResolvedValueOnce({
        ...INVESTMENT,
        transaction_price: 53_000_000,
        units: [...INVESTMENT.units, { unit_id: 'deal-d', ordinal: 3, label: null, unit_kind: 'property', acquisition_month: 0, disposition_month: null }],
      });
    renderWorkspace();
    await user.click(await screen.findByRole('tab', { name: 'Units' }));
    await user.click(screen.getByRole('button', { name: 'Add Unit' }));
    const price = screen.getByLabelText('Resulting Transaction Price') as HTMLInputElement;
    expect(price.value).toBe('');
    await user.selectOptions(screen.getByLabelText('Deal'), 'deal-d');
    await user.click(screen.getAllByRole('button', { name: 'Add Unit' })[1]);
    expect(mockAdd).not.toHaveBeenCalled();

    await user.type(price, '45000000');
    await user.click(screen.getAllByRole('button', { name: 'Add Unit' })[1]);
    const refusal = await screen.findByText(/do not reconcile to the Investment transaction price/);
    expect((refusal.closest('li') as HTMLElement).textContent).toContain('Bayside Flex');
    expect(mockAdd).toHaveBeenLastCalledWith('inv-1', { unit_id: 'deal-d', label: null, unit_kind: 'property', transaction_price: 45_000_000 });

    await user.click(price);
    await user.keyboard('{Control>}a{/Control}53000000');
    await user.click(screen.getAllByRole('button', { name: 'Add Unit' })[1]);
    await waitFor(() =>
      expect(mockAdd).toHaveBeenLastCalledWith('inv-1', { unit_id: 'deal-d', label: null, unit_kind: 'property', transaction_price: 53_000_000 }),
    );
    await waitFor(() => expect(screen.queryByLabelText('Resulting Transaction Price')).toBeNull());
    expect(within(panel('Units')).getByRole('rowheader', { name: /Bayside Flex/ })).toBeTruthy();
  });

  it('removes a Unit in one request with the stated price; a refusal changes nothing', async () => {
    const user = userEvent.setup();
    mockRemove
      .mockRejectedValueOnce(
        new InvestmentApiError("Unit 'deal-b' is still addressed by strategy 'Sell Office'.", 409, {
          investmentIssues: [],
          variantIssues: [],
          planIssues: [],
          reasons: ["Unit 'deal-b' is still addressed by strategy 'Sell Office'. Remove those overrides and overlays first."],
        }),
      )
      .mockResolvedValueOnce({ ...INVESTMENT, transaction_price: 25_000_000, units: [INVESTMENT.units[0], INVESTMENT.units[2]] });
    renderWorkspace();
    await user.click(await screen.findByRole('tab', { name: 'Units' }));
    await user.click(screen.getByRole('button', { name: 'Remove Harbor Office' }));
    const confirm = screen.getByRole('group', { name: 'Confirm removing Harbor Office' });
    expect(within(confirm).getByText(REMOVE_UNIT_CONSEQUENCES)).toBeTruthy();
    await user.type(within(confirm).getByLabelText('Resulting Transaction Price'), '25000000');
    await user.click(within(confirm).getByRole('button', { name: 'Remove Unit' }));
    expect(await within(confirm).findByText(/Unit 'Harbor Office' is still addressed by strategy 'Sell Office'\./)).toBeTruthy();
    expect(mockRemove).toHaveBeenCalledTimes(1);
    expect(mockRemove).toHaveBeenCalledWith('inv-1', 'deal-b', 25_000_000);
    expect(mockDetails).not.toHaveBeenCalled();
    expect(within(panel('Units')).getByRole('rowheader', { name: /Harbor Office/ })).toBeTruthy();

    await user.click(within(confirm).getByRole('button', { name: 'Remove Unit' }));
    await waitFor(() => expect(mockRemove).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(within(panel('Units')).queryByRole('rowheader', { name: /Harbor Office/ })).toBeNull());
    expect(mockDetails).not.toHaveBeenCalled();
    expect(handlers.onChanged).toHaveBeenCalled();
  });

  it('never removes the last Unit', async () => {
    const user = userEvent.setup();
    mockGet.mockResolvedValue({ ...INVESTMENT, units: [INVESTMENT.units[0]] });
    renderWorkspace();
    await user.click(await screen.findByRole('tab', { name: 'Units' }));
    expect((screen.getByRole('button', { name: 'Remove Harbor Retail' }) as HTMLButtonElement).disabled).toBe(true);
    expect(within(panel('Units')).getByText(LAST_UNIT_MESSAGE)).toBeTruthy();
  });
});

// =============================================================================
// Deleting the Investment
// =============================================================================

describe('Delete Investment', () => {
  it('says the Deals are released, not deleted, and deletes only on confirmation', async () => {
    const user = userEvent.setup();
    mockDelete.mockResolvedValue(undefined);
    renderWorkspace();
    await user.click(await screen.findByRole('button', { name: 'Delete Investment' }));
    const confirm = screen.getByRole('group', { name: 'Confirm deleting Harbor Portfolio' });
    expect(within(confirm).getByText(DELETE_INVESTMENT_CONSEQUENCES)).toBeTruthy();
    expect(DELETE_INVESTMENT_CONSEQUENCES).toContain('does not delete the Deals');
    expect(mockDelete).not.toHaveBeenCalled();
    await user.click(within(confirm).getByRole('button', { name: 'Delete Investment' }));
    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith('inv-1'));
    expect(handlers.onDeleted).toHaveBeenCalledTimes(1);
  });
});
