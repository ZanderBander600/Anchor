/**
 * Phase 7 Gate P7.6 -- Strategies, Scenarios and the Decision Matrix of a
 * visible Investment, driven through `RiskDecisionWorkspace` in its Investment
 * scope against a mocked `api.ts`.
 *
 * One implementation, two scopes: these tests prove the Investment scope uses
 * the Investment-scoped routes (never the Deal-scoped or one-unit ones), that a
 * Strategy decides for several Units at once -- each Unit's domains prefilled
 * from that Unit's own saved Deal -- that a Scenario row names its Unit and
 * offers only that Unit's mode's assumptions, and that the matrix is the
 * consolidated one, every invalid cell naming its Unit.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  analyzeDecisionMatrix,
  analyzeInvestmentDecisionMatrix,
  createDealScenario,
  createDealStrategy,
  createInvestmentScenario,
  fetchScenarioTargetCatalog,
  fetchStrategyTargetCatalog,
  getDeal,
  InvestmentStrategyApiError,
  listDealScenarios,
  listDealStrategies,
  listInvestmentScenarios,
  listInvestmentStrategies,
  saveInvestmentStrategy,
  updateInvestmentScenario,
} from './api';
import { RiskDecisionWorkspace } from './components/RiskDecisionWorkspace';
import type { RiskDecisionWorkspaceProps } from './components/RiskDecisionWorkspace';
import type { DecisionMatrix, DecisionMetricSpec } from './decisionTypes';
import {
  INVESTMENT_DIRTY_MESSAGE,
  INVESTMENT_MATRIX_COPY,
  UNIT_OF_INVESTMENT_NOTICE,
} from './investmentCatalog';
import type { DecisionUnit, InvestmentDecisionScope } from './investmentCatalog';
import type { InvestmentDecisionMatrixReport } from './investmentTypes';
import type { InvestmentScenario } from './scenarioTypes';
import { BASE_PREFILL_UNAVAILABLE_MESSAGE } from './strategyCatalog';
import type { InvestmentStrategy } from './strategyTypes';
import type { AcquisitionRequest, Deal } from './types';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    analyzeDecisionMatrix: vi.fn(),
    analyzeInvestmentDecisionMatrix: vi.fn(),
    createDealScenario: vi.fn(),
    createDealStrategy: vi.fn(),
    createInvestmentScenario: vi.fn(),
    fetchScenarioTargetCatalog: vi.fn(),
    fetchStrategyTargetCatalog: vi.fn(),
    getDeal: vi.fn(),
    listDealScenarios: vi.fn(),
    listDealStrategies: vi.fn(),
    listInvestmentScenarios: vi.fn(),
    listInvestmentStrategies: vi.fn(),
    saveInvestmentStrategy: vi.fn(),
    updateInvestmentScenario: vi.fn(),
  };
});

const mockListStrategies = vi.mocked(listInvestmentStrategies);
const mockListScenarios = vi.mocked(listInvestmentScenarios);
const mockSaveStrategy = vi.mocked(saveInvestmentStrategy);
const mockCreateScenario = vi.mocked(createInvestmentScenario);
const mockUpdateScenario = vi.mocked(updateInvestmentScenario);
const mockGetDeal = vi.mocked(getDeal);
const mockMatrix = vi.mocked(analyzeInvestmentDecisionMatrix);

// =============================================================================
// Fixtures: three Units, one per operating mode
// =============================================================================

const UNITS: DecisionUnit[] = [
  { unitId: 'deal-a', dealName: 'Harbor Retail', label: 'Podium', operatingMode: 'quick', savedAt: 'a-1' },
  { unitId: 'deal-b', dealName: 'Harbor Office', label: null, operatingMode: 'detailed', savedAt: 'b-1' },
  { unitId: 'deal-c', dealName: 'Harbor Industrial', label: null, operatingMode: 'lease_level', savedAt: 'c-1' },
];

const SCOPE: InvestmentDecisionScope = { investmentId: 'inv-1', units: UNITS, stateToken: 'state-1' };

function terms(purchasePrice: number): AcquisitionRequest {
  return {
    purchase_price: purchasePrice,
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
  const inputs = terms(price);
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
    updated_at: `${id}-saved`,
  } as unknown as Deal;
}

const DEALS: Record<string, Deal> = {
  'deal-a': deal('deal-a', 'Harbor Retail', 'quick', 12_500_000),
  'deal-b': deal('deal-b', 'Harbor Office', 'detailed', 20_000_000),
  'deal-c': deal('deal-c', 'Harbor Industrial', 'lease_level', 12_500_000),
};

const STRATEGY_CATALOG = {
  quick: [
    { target: 'exit_cap_rate', units: 'decimal rate (0.0725 is 7.25%)' },
    { target: 'noi_growth', units: 'decimal annual rate (0.03 is 3%)' },
  ],
  detailed: [
    { target: 'exit_cap_rate', units: 'decimal rate (0.0725 is 7.25%)' },
    { target: 'expense_growth', units: 'decimal annual rate (0.03 is 3%)' },
  ],
  lease_level: [
    { target: 'exit_cap_rate', units: 'decimal rate (0.0725 is 7.25%)' },
    { target: 'market_rent_psf', units: '$/SF per year' },
  ],
};

const SCENARIO_CATALOG = {
  quick: [
    { target: 'exit_cap_rate', allowed_operations: ['set', 'add'], units: 'decimal rate (0.0725 is 7.25%)' },
    { target: 'noi_growth', allowed_operations: ['set', 'add'], units: 'decimal annual rate (0.03 is 3%)' },
  ],
  detailed: [
    { target: 'exit_cap_rate', allowed_operations: ['set', 'add'], units: 'decimal rate (0.0725 is 7.25%)' },
    { target: 'expense_growth', allowed_operations: ['set', 'add'], units: 'decimal annual rate (0.03 is 3%)' },
  ],
  lease_level: [{ target: 'market_rent_psf', allowed_operations: ['set', 'scale'], units: '$/SF per year' }],
};

function strategy(id: string, name: string, overlays: InvestmentStrategy['strategy']['overlays']): InvestmentStrategy {
  return {
    investment_id: 'inv-1',
    strategy: { strategy_id: id, name, description: null, overlays },
    created_at: '2026-09-14T00:00:00+00:00',
    updated_at: '2026-09-14T00:00:00+00:00',
  };
}

function scenario(id: string, name: string, overrides: InvestmentScenario['scenario']['overrides']): InvestmentScenario {
  return {
    investment_id: 'inv-1',
    scenario: { scenario_id: id, name, description: null, overrides },
    created_at: '2026-09-14T00:00:00+00:00',
    updated_at: '2026-09-14T00:00:00+00:00',
  };
}

function props(overrides: Partial<RiskDecisionWorkspaceProps> = {}): RiskDecisionWorkspaceProps {
  return {
    operatingMode: null,
    dealId: null,
    isDirty: false,
    savedAt: null,
    isActive: true,
    view: 'strategies',
    investment: SCOPE,
    ...overrides,
  };
}

beforeEach(() => {
  mockListStrategies.mockResolvedValue([]);
  mockListScenarios.mockResolvedValue([]);
  vi.mocked(fetchStrategyTargetCatalog).mockResolvedValue(STRATEGY_CATALOG);
  vi.mocked(fetchScenarioTargetCatalog).mockResolvedValue(
    SCENARIO_CATALOG as unknown as Awaited<ReturnType<typeof fetchScenarioTargetCatalog>>,
  );
  mockGetDeal.mockImplementation(async (id) => DEALS[id]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function unitSection(name: string): HTMLElement {
  return screen.getByRole('region', { name });
}

async function openNewStrategy(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: 'Add Strategy' }));
  await screen.findByRole('heading', { name: 'Unit Decisions' });
}

// =============================================================================
// Routes
// =============================================================================

describe('a visible Investment’s decision set lives on its own routes', () => {
  it('reads Strategies and Scenarios from the Investment routes, never the Deal ones', async () => {
    render(<RiskDecisionWorkspace {...props()} />);
    await screen.findByRole('button', { name: 'Add Strategy' });
    await waitFor(() => expect(mockListStrategies).toHaveBeenCalledWith('inv-1'));
    expect(mockListScenarios).toHaveBeenCalledWith('inv-1');
    expect(listDealStrategies).not.toHaveBeenCalled();
    expect(listDealScenarios).not.toHaveBeenCalled();
  });

  it('asks for nothing -- and points to the Investment -- for a Deal that is one of its Units', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(
      <RiskDecisionWorkspace
        operatingMode="quick"
        dealId="deal-a"
        isDirty={false}
        savedAt="a-1"
        isActive
        view="strategies"
        memberOf={{ investmentName: 'Harbor Portfolio', onOpen }}
      />,
    );
    // Every decision view says so; only the one on screen is reachable. Four
    // since P7.8B, which added Capital Structure beside the other three, and
    // five since P7.9 Stage 3, which adds Partnership: a Unit of a visible
    // Investment states its structure and its partnership on the Investment,
    // exactly as it states its strategies and scenarios there.
    expect(screen.getAllByText(UNIT_OF_INVESTMENT_NOTICE)).toHaveLength(5);
    await user.click(screen.getByRole('button', { name: 'Open Harbor Portfolio' }));
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(listDealStrategies).not.toHaveBeenCalled();
    expect(listDealScenarios).not.toHaveBeenCalled();
    expect(mockListStrategies).not.toHaveBeenCalled();
  });
});

// =============================================================================
// Multi-unit Strategies
// =============================================================================

describe('a multi-unit Strategy', () => {
  it('holds one section per Unit, each naming its Deal, label and mode', async () => {
    const user = userEvent.setup();
    render(<RiskDecisionWorkspace {...props()} />);
    await openNewStrategy(user);
    const retail = unitSection('Harbor Retail (Podium)');
    expect(within(retail).getByText(/Podium · /)).toBeTruthy();
    expect(unitSection('Harbor Office')).toBeTruthy();
    expect(unitSection('Harbor Industrial')).toBeTruthy();
    for (const name of ['Harbor Retail (Podium)', 'Harbor Office', 'Harbor Industrial']) {
      const section = unitSection(name);
      for (const domain of ['Acquisition', 'Financing', 'Business Plan', 'Operating Outcome', 'Disposition']) {
        expect(within(section).getByRole('radiogroup', { name: domain }), `${name} ${domain}`).toBeTruthy();
      }
    }
  });

  it('prefills each Unit from its own saved Deal; one failed read disables only that Unit', async () => {
    const user = userEvent.setup();
    let officeFails = true;
    mockGetDeal.mockImplementation(async (id) => {
      if (id === 'deal-b' && officeFails) {
        throw new Error('unreachable');
      }
      return DEALS[id];
    });
    render(<RiskDecisionWorkspace {...props()} />);
    await openNewStrategy(user);

    const office = unitSection('Harbor Office');
    await within(office).findByText(BASE_PREFILL_UNAVAILABLE_MESSAGE);
    const officeAcquisition = within(office).getByRole('radiogroup', { name: 'Acquisition' });
    expect((within(officeAcquisition).getByRole('radio', { name: 'Strategy-specific' }) as HTMLInputElement).disabled).toBe(true);

    // The other Units are usable, each from its own Deal.
    const retail = unitSection('Harbor Retail (Podium)');
    await user.click(within(within(retail).getByRole('radiogroup', { name: 'Acquisition' })).getByRole('radio', { name: 'Strategy-specific' }));
    expect((within(retail).getByLabelText('Purchase Price') as HTMLInputElement).value).toBe('12,500,000');

    officeFails = false;
    await user.click(within(office).getByRole('button', { name: 'Retry' }));
    await waitFor(() =>
      expect(
        (within(within(office).getByRole('radiogroup', { name: 'Acquisition' })).getByRole('radio', { name: 'Strategy-specific' }) as HTMLInputElement).disabled,
      ).toBe(false),
    );
    await user.click(within(within(office).getByRole('radiogroup', { name: 'Acquisition' })).getByRole('radio', { name: 'Strategy-specific' }));
    expect((within(office).getByLabelText('Purchase Price') as HTMLInputElement).value).toBe('20,000,000');
  });

  it('offers each Unit only its own mode’s operating outcomes', async () => {
    const user = userEvent.setup();
    render(<RiskDecisionWorkspace {...props()} />);
    await openNewStrategy(user);
    const industrial = unitSection('Harbor Industrial');
    await user.click(within(within(industrial).getByRole('radiogroup', { name: 'Operating Outcome' })).getByRole('radio', { name: 'Strategy-specific' }));
    const industrialOptions = within(within(industrial).getByLabelText('Assumption', { exact: true })).getAllByRole('option').map((option) => option.textContent);
    expect(industrialOptions).toContain('Market Rent');
    const retail = unitSection('Harbor Retail (Podium)');
    await user.click(within(within(retail).getByRole('radiogroup', { name: 'Operating Outcome' })).getByRole('radio', { name: 'Strategy-specific' }));
    const retailOptions = within(within(retail).getByLabelText('Assumption', { exact: true })).getAllByRole('option').map((option) => option.textContent);
    expect(retailOptions).toContain('NOI Growth');
    expect(retailOptions).not.toContain('Market Rent');
  });

  it('saves one Strategy deciding for several Units, on the Investment route', async () => {
    const user = userEvent.setup();
    mockSaveStrategy.mockImplementation(async (_id, _strategyId, draft) => strategy('st-new', draft.name, draft.overlays));
    render(<RiskDecisionWorkspace {...props()} />);
    await openNewStrategy(user);
    await user.type(screen.getByLabelText('Strategy Name'), 'Mixed Plan');

    const retail = unitSection('Harbor Retail (Podium)');
    await within(retail).findByText(/Inherits Base/, { selector: '.strategy-domain-inherit-label' }).catch(() => undefined);
    await waitFor(() =>
      expect(
        (within(within(retail).getByRole('radiogroup', { name: 'Acquisition' })).getByRole('radio', { name: 'Strategy-specific' }) as HTMLInputElement).disabled,
      ).toBe(false),
    );
    await user.click(within(within(retail).getByRole('radiogroup', { name: 'Acquisition' })).getByRole('radio', { name: 'Strategy-specific' }));

    const office = unitSection('Harbor Office');
    await user.click(within(within(office).getByRole('radiogroup', { name: 'Business Plan' })).getByRole('radio', { name: 'No Business Plan' }));

    const industrial = unitSection('Harbor Industrial');
    await user.click(within(within(industrial).getByRole('radiogroup', { name: 'Operating Outcome' })).getByRole('radio', { name: 'Strategy-specific' }));
    await user.selectOptions(within(industrial).getByLabelText('Assumption', { exact: true }), 'market_rent_psf');
    await user.type(within(industrial).getByLabelText(/^Value/), '32.5');

    await user.click(screen.getByRole('button', { name: 'Save Strategy' }));
    await waitFor(() => expect(mockSaveStrategy).toHaveBeenCalledTimes(1));
    expect(mockSaveStrategy).toHaveBeenCalledWith('inv-1', null, {
      name: 'Mixed Plan',
      description: null,
      overlays: [
        { unit_id: 'deal-a', domain: 'acquisition', content: { purchase_price: 12_500_000, acquisition_cost_pct: 0.02 } },
        { unit_id: 'deal-b', domain: 'business_plan', content: { capital_items: [], owner_expense_items: [] } },
        {
          unit_id: 'deal-c',
          domain: 'operating_outcome',
          content: { outcomes: [{ target: 'market_rent_psf', operation: 'set', value: 32.5 }] },
        },
      ],
    });
    expect(createDealStrategy).not.toHaveBeenCalled();
    expect(await screen.findByText('Mixed Plan')).toBeTruthy();
  });

  it('reopens a saved multi-unit Strategy with every overlay on its own Unit', async () => {
    const user = userEvent.setup();
    mockListStrategies.mockResolvedValue([
      strategy('st-1', 'Sell Retail Late', [
        { unit_id: 'deal-a', domain: 'disposition', content: { hold_period: 7 } },
        { unit_id: 'deal-c', domain: 'operating_outcome', content: { outcomes: [{ target: 'market_rent_psf', operation: 'set', value: 30 }] } },
      ]),
    ]);
    render(<RiskDecisionWorkspace {...props()} />);
    // The list names each overlay's Unit.
    expect(await screen.findByText('Harbor Retail (Podium) · 7-year hold')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Edit Sell Retail Late' }));
    const retail = unitSection('Harbor Retail (Podium)');
    expect((within(retail).getByLabelText('Hold Period') as HTMLInputElement).value).toBe('7');
    const industrial = unitSection('Harbor Industrial');
    expect((within(industrial).getByLabelText('Assumption', { exact: true }) as HTMLSelectElement).value).toBe('market_rent_psf');
    expect((within(industrial).getByLabelText(/^Value/) as HTMLInputElement).value).toBe('30');
    const office = unitSection('Harbor Office');
    expect(within(office).queryByLabelText('Hold Period')).toBeNull();
  });

  it('places a refusal on the Unit domain it names, the Unit named rather than its id', async () => {
    const user = userEvent.setup();
    mockSaveStrategy.mockRejectedValue(
      new InvestmentStrategyApiError(
        'refused',
        422,
        {
          issues: [],
          strategyIssues: [
            {
              stage: 'resolved_inputs',
              code: 'invalid_ltv',
              message: "Unit 'deal-b': ltv must be below 1.",
              domain: 'financing',
              unit_id: 'deal-b',
              field: 'ltv',
              target: null,
              source_code: null,
            },
          ],
          planIssues: [],
          reasons: ["Unit 'deal-b': ltv must be below 1."],
        },
        [],
      ),
    );
    render(<RiskDecisionWorkspace {...props()} />);
    await openNewStrategy(user);
    await user.type(screen.getByLabelText('Strategy Name'), 'Refused');
    await user.click(screen.getByRole('button', { name: 'Save Strategy' }));
    const office = unitSection('Harbor Office');
    expect(await within(office).findByText("Unit 'Harbor Office': ltv must be below 1.")).toBeTruthy();
    expect(screen.queryByText(/deal-b/)).toBeNull();
  });

  it('keeps an open draft locked, not lost, while the Investment has unsaved changes', async () => {
    const user = userEvent.setup();
    const { rerender } = render(<RiskDecisionWorkspace {...props()} />);
    await openNewStrategy(user);
    await user.type(screen.getByLabelText('Strategy Name'), 'Draft');
    rerender(<RiskDecisionWorkspace {...props({ isDirty: true })} />);
    expect(screen.getAllByText(INVESTMENT_DIRTY_MESSAGE).length).toBeGreaterThan(0);
    expect((screen.getByLabelText('Strategy Name') as HTMLInputElement).value).toBe('Draft');
    expect((screen.getByLabelText('Strategy Name') as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Save Strategy' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Cancel' }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole('button', { name: 'Add Strategy' }) as HTMLButtonElement).disabled).toBe(true);
  });
});

// =============================================================================
// Multi-unit Scenarios
// =============================================================================

describe('a multi-unit Scenario', () => {
  function rows() {
    return screen.getAllByLabelText('Unit', { exact: true }) as HTMLSelectElement[];
  }

  it('names the Unit of each row and offers only that Unit’s assumptions, once each', async () => {
    const user = userEvent.setup();
    render(<RiskDecisionWorkspace {...props({ view: 'scenarios' })} />);
    await user.click(await screen.findByRole('button', { name: 'Add Scenario' }));
    const [firstUnit] = rows();
    const firstAssumption = screen.getAllByLabelText('Assumption', { exact: true })[0] as HTMLSelectElement;
    expect(firstAssumption.disabled).toBe(true);

    await user.selectOptions(firstUnit, 'deal-c');
    const industrialOptions = within(firstAssumption).getAllByRole('option').map((option) => option.textContent);
    expect(industrialOptions).toEqual(['Choose assumption…', 'Market Rent']);

    await user.selectOptions(firstUnit, 'deal-a');
    await user.selectOptions(firstAssumption, 'exit_cap_rate');
    await user.click(screen.getByRole('button', { name: 'Add Override' }));
    const secondUnit = rows()[1];
    const secondAssumption = screen.getAllByLabelText('Assumption', { exact: true })[1] as HTMLSelectElement;
    await user.selectOptions(secondUnit, 'deal-a');
    expect(within(secondAssumption).getAllByRole('option').map((option) => option.textContent)).not.toContain('Exit Cap Rate');
    await user.selectOptions(secondUnit, 'deal-b');
    expect(within(secondAssumption).getAllByRole('option').map((option) => option.textContent)).toContain('Exit Cap Rate');
  });

  it('saves on the Investment route, each override addressed to its Unit, and edits in place', async () => {
    const user = userEvent.setup();
    mockCreateScenario.mockImplementation(async (_id, draft) => scenario('sc-new', draft.name, draft.overrides));
    render(<RiskDecisionWorkspace {...props({ view: 'scenarios' })} />);
    await user.click(await screen.findByRole('button', { name: 'Add Scenario' }));
    await user.type(screen.getByLabelText('Scenario Name'), 'Downside');

    const plan: [string, string, string, string][] = [
      ['deal-a', 'exit_cap_rate', 'add', '0.5'],
      ['deal-b', 'expense_growth', 'add', '1'],
      ['deal-c', 'market_rent_psf', 'scale', '0.9'],
    ];
    for (const [index, [unit, target, operation, value]] of plan.entries()) {
      if (index > 0) {
        await user.click(screen.getByRole('button', { name: 'Add Override' }));
      }
      await user.selectOptions(rows()[index], unit);
      await user.selectOptions(screen.getAllByLabelText('Assumption', { exact: true })[index], target);
      await user.selectOptions(screen.getAllByLabelText(/^Operation/)[index], operation);
      await user.type(screen.getAllByLabelText(/^Value/)[index], value);
    }
    await user.click(screen.getByRole('button', { name: 'Save Scenario' }));
    await waitFor(() => expect(mockCreateScenario).toHaveBeenCalledTimes(1));
    expect(mockCreateScenario).toHaveBeenCalledWith('inv-1', {
      name: 'Downside',
      description: null,
      overrides: [
        { unit_id: 'deal-a', target: 'exit_cap_rate', operation: 'add', value: 0.005 },
        { unit_id: 'deal-b', target: 'expense_growth', operation: 'add', value: 0.01 },
        { unit_id: 'deal-c', target: 'market_rent_psf', operation: 'scale', value: 0.9 },
      ],
    });
    expect(createDealScenario).not.toHaveBeenCalled();
    expect(await screen.findByText(/Harbor Retail \(Podium\) · Exit Cap Rate: Add \+0\.5% pts/)).toBeTruthy();

    mockUpdateScenario.mockImplementation(async (_id, scenarioId, draft) => scenario(scenarioId, draft.name, draft.overrides));
    await user.click(screen.getByRole('button', { name: 'Edit Downside' }));
    expect(rows().map((select) => select.value)).toEqual(['deal-a', 'deal-b', 'deal-c']);
    await user.click(screen.getByRole('button', { name: 'Save Scenario' }));
    await waitFor(() => expect(mockUpdateScenario).toHaveBeenCalledTimes(1));
    expect(mockUpdateScenario.mock.calls[0][0]).toBe('inv-1');
    expect(mockUpdateScenario.mock.calls[0][1]).toBe('sc-new');
  });
});

// =============================================================================
// The consolidated Decision Matrix
// =============================================================================

const SPECS: DecisionMetricSpec[] = [
  { metric: 'levered_irr', label: 'Levered IRR', unit: 'rate', direction: 'higher_is_better', horizon_dependent: false },
  { metric: 'min_dscr', label: 'Minimum Aggregate DSCR', unit: 'multiple', direction: 'higher_is_better', horizon_dependent: true },
];

function figure(metric: string, value: number | null) {
  return { metric, value, irr_status: null, reason: null, message: null };
}

function validCell(strategyId: string, scenarioId: string, irr: number, dscr: number, delta: number | null) {
  return {
    strategy_id: strategyId,
    scenario_id: scenarioId,
    status: 'valid' as const,
    issues: [],
    source_fingerprint: `fp-${strategyId}-${scenarioId}`,
    cache_status: 'bypassed' as const,
    hold_period: 5,
    results: null,
    metrics: [figure('levered_irr', irr), figure('min_dscr', dscr)],
    deltas: [
      { metric: 'levered_irr', value: delta, is_baseline: scenarioId === 'base', reason: null, message: null, sources: [] },
      { metric: 'min_dscr', value: null, is_baseline: scenarioId === 'base', reason: null, message: null, sources: [] },
    ],
  };
}

const MATRIX: DecisionMatrix = {
  perspective: 'project',
  strategies: [
    { strategy_id: 'base', name: 'Base Strategy', is_base: true, hold_period: 5 },
    { strategy_id: 'st-1', name: 'Sell Retail Late', is_base: false, hold_period: null },
  ],
  scenarios: [
    { scenario_id: 'base', name: 'Base', is_base: true },
    { scenario_id: 'sc-1', name: 'Downside', is_base: false },
  ],
  metrics: SPECS,
  omitted_metrics: [],
  hold_periods: [5],
  cross_scenario_figures: true,
  cells: [
    validCell('base', 'base', 0.1411, 1.52, null),
    validCell('base', 'sc-1', 0.1023, 1.31, -0.0377),
    {
      strategy_id: 'st-1',
      scenario_id: 'base',
      status: 'invalid',
      issues: [
        {
          source: 'investment',
          code: 'hold_period_mismatch',
          message: "The Units' hold periods differ (deal-a: 7, deal-b: 5, deal-c: 5).",
          field: 'units[deal-a].hold_period',
        },
      ],
      source_fingerprint: null,
      cache_status: null,
      hold_period: null,
      results: null,
      metrics: [],
      deltas: [],
    },
    validCell('st-1', 'sc-1', 0.0987, 1.28, null),
  ],
  strategy_figures: [
    {
      strategy_id: 'base',
      worst_cases: [
        { metric: 'levered_irr', direction: 'higher_is_better', value: 0.1023, scenario_id: 'sc-1', scenario_name: 'Downside', reason: null, message: null, unavailable_scenario_ids: [], sources: [] },
        { metric: 'min_dscr', direction: 'higher_is_better', value: 1.31, scenario_id: 'sc-1', scenario_name: 'Downside', reason: null, message: null, unavailable_scenario_ids: [], sources: [] },
      ],
      ranges: [
        { metric: 'levered_irr', minimum: 0.1023, minimum_scenario_id: 'sc-1', maximum: 0.1411, maximum_scenario_id: 'base', spread: 0.0388, reason: null, message: null, unavailable_scenario_ids: [], sources: [] },
        { metric: 'min_dscr', minimum: 1.31, minimum_scenario_id: 'sc-1', maximum: 1.52, maximum_scenario_id: 'base', spread: 0.21, reason: null, message: null, unavailable_scenario_ids: [], sources: [] },
      ],
    },
    {
      strategy_id: 'st-1',
      worst_cases: [
        { metric: 'levered_irr', direction: 'higher_is_better', value: null, scenario_id: null, scenario_name: null, reason: 'base_scenario_invalid', message: 'The Base scenario of this strategy is an invalid variant.', unavailable_scenario_ids: ['base'], sources: [] },
        { metric: 'min_dscr', direction: 'higher_is_better', value: null, scenario_id: null, scenario_name: null, reason: 'base_scenario_invalid', message: 'The Base scenario of this strategy is an invalid variant.', unavailable_scenario_ids: ['base'], sources: [] },
      ],
      ranges: [
        { metric: 'levered_irr', minimum: null, minimum_scenario_id: null, maximum: null, maximum_scenario_id: null, spread: null, reason: 'base_scenario_invalid', message: 'The Base scenario of this strategy is an invalid variant.', unavailable_scenario_ids: ['base'], sources: [] },
        { metric: 'min_dscr', minimum: null, minimum_scenario_id: null, maximum: null, maximum_scenario_id: null, spread: null, reason: 'base_scenario_invalid', message: 'The Base scenario of this strategy is an invalid variant.', unavailable_scenario_ids: ['base'], sources: [] },
      ],
    },
  ],
  matrix_fingerprint: 'matrix-fp',
  matrix_fingerprint_reason: null,
};

const REPORT: InvestmentDecisionMatrixReport = {
  investment_id: 'inv-1',
  units: [
    { unit_id: 'deal-a', operating_mode: 'quick' },
    { unit_id: 'deal-b', operating_mode: 'detailed' },
    { unit_id: 'deal-c', operating_mode: 'lease_level' },
  ],
  matrix: MATRIX,
};

describe('the consolidated Decision Matrix', () => {
  beforeEach(() => {
    mockListStrategies.mockResolvedValue([
      strategy('st-1', 'Sell Retail Late', [{ unit_id: 'deal-a', domain: 'disposition', content: { hold_period: 7 } }]),
    ]);
    mockListScenarios.mockResolvedValue([
      scenario('sc-1', 'Downside', [{ unit_id: 'deal-a', target: 'exit_cap_rate', operation: 'add', value: 0.005 }]),
    ]);
    mockMatrix.mockResolvedValue(REPORT);
  });

  it('runs the Investment matrix, shows the backend’s figures and names each invalid Unit', async () => {
    const user = userEvent.setup();
    render(<RiskDecisionWorkspace {...props({ view: 'matrix' })} />);
    expect(screen.getByText(INVESTMENT_MATRIX_COPY.subtitle)).toBeTruthy();
    await user.click(await screen.findByRole('button', { name: 'Run Decision Matrix' }));
    await waitFor(() => expect(mockMatrix).toHaveBeenCalledWith('inv-1'));
    expect(analyzeDecisionMatrix).not.toHaveBeenCalled();

    const table = await screen.findByRole('table');
    expect(within(table).getAllByRole('rowheader', { name: /Minimum Aggregate DSCR/ })).toHaveLength(2);
    expect(within(table).queryByText(/^Minimum DSCR/)).toBeNull();
    // Backend figures, formatted: never a subtraction of two cells.
    expect(within(table).getByText('-3.77 pts vs Base')).toBeTruthy();
    expect(within(table).getAllByText('3.88 pts').length).toBeGreaterThan(0);

    const invalid = within(table).getByText('Invalid variant').closest('td') as HTMLElement;
    expect(invalid.querySelector('.decision-matrix-reason-unit')?.textContent).toBe('Harbor Retail (Podium): ');
    expect(within(invalid).getByText(/All Units in one Investment variant must use the same hold period\./)).toBeTruthy();
    expect(invalid.textContent).toContain('Harbor Retail (Podium): 7, Harbor Office: 5, Harbor Industrial: 5');
    expect(invalid.textContent).not.toContain('deal-a');
    // Every other cell stands.
    expect(within(table).getByText('9.87%')).toBeTruthy();
  });

  it('is out of date as soon as the saved Investment state moves', async () => {
    const user = userEvent.setup();
    const { rerender } = render(<RiskDecisionWorkspace {...props({ view: 'matrix' })} />);
    await user.click(await screen.findByRole('button', { name: 'Run Decision Matrix' }));
    await screen.findByRole('table');
    rerender(<RiskDecisionWorkspace {...props({ view: 'matrix', investment: { ...SCOPE, stateToken: 'state-2' } })} />);
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.getByText(INVESTMENT_MATRIX_COPY.stale)).toBeTruthy();
    rerender(<RiskDecisionWorkspace {...props({ view: 'matrix', isDirty: true, investment: { ...SCOPE, stateToken: 'state-2' } })} />);
    expect(screen.getByText(INVESTMENT_MATRIX_COPY.dirty)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Refresh Matrix' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
