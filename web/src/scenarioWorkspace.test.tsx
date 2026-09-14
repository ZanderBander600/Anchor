/**
 * Phase 7 Gate P7.3 -- the Scenario workspace: state, editor and comparison.
 *
 * Drives `ScenarioWorkspace` (and through it `useScenarios`) against a mocked
 * `api.ts`. The error classes stay real, so a refusal reaches the hook exactly
 * as the client would raise it. Every figure asserted here is one field of a
 * backend result, formatted. The fixtures are chosen so that any browser
 * arithmetic -- a delta, a sum, a fallback -- would produce a different string
 * and fail.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  analyzeAcquisition,
  analyzeDetailedAcquisition,
  analyzeInvestmentScenario,
  analyzeLeaseLevelAcquisition,
  ApiError,
  createDealScenario,
  deleteInvestmentScenario,
  fetchScenarioTargetCatalog,
  getDeal,
  listDealScenarios,
  ScenarioApiError,
  updateInvestmentScenario,
} from './api';
import { ScenarioWorkspace } from './components/ScenarioWorkspace';
import type { ScenarioWorkspaceProps } from './components/ScenarioWorkspace';
import type { LeaseLevelAcquisitionResults } from './leaseLevelTypes';
import {
  DIRTY_COMPARISON_MESSAGE,
  SAVE_BEFORE_SCENARIOS_MESSAGE,
  STALE_COMPARISON_MESSAGE,
} from './scenarioComparison';
import type {
  InvestmentScenario,
  ScenarioIssue,
  ScenarioOverride,
  ScenarioTargetCatalog,
  ScenarioVariantAnalysis,
  VariantCacheStatus,
} from './scenarioTypes';
import type {
  AcquisitionRequest,
  AcquisitionResults,
  AcquisitionTermsRequest,
  Deal,
  DetailedAcquisitionResults,
  DetailedOperatingInputsRequest,
  OperatingMode,
} from './types';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    analyzeAcquisition: vi.fn(),
    analyzeDetailedAcquisition: vi.fn(),
    analyzeLeaseLevelAcquisition: vi.fn(),
    analyzeInvestmentScenario: vi.fn(),
    createDealScenario: vi.fn(),
    deleteInvestmentScenario: vi.fn(),
    fetchScenarioTargetCatalog: vi.fn(),
    getDeal: vi.fn(),
    listDealScenarios: vi.fn(),
    updateInvestmentScenario: vi.fn(),
  };
});

const mockList = vi.mocked(listDealScenarios);
const mockCatalog = vi.mocked(fetchScenarioTargetCatalog);
const mockCreate = vi.mocked(createDealScenario);
const mockUpdate = vi.mocked(updateInvestmentScenario);
const mockDelete = vi.mocked(deleteInvestmentScenario);
const mockAnalyzeScenario = vi.mocked(analyzeInvestmentScenario);
const mockGetDeal = vi.mocked(getDeal);
const mockAnalyzeQuick = vi.mocked(analyzeAcquisition);
const mockAnalyzeDetailed = vi.mocked(analyzeDetailedAcquisition);
const mockAnalyzeLeaseLevel = vi.mocked(analyzeLeaseLevelAcquisition);

// =============================================================================
// Fixtures
// =============================================================================

const RATE = 'decimal rate (0.0725 is 7.25%)';
const GROWTH = 'decimal annual rate (0.03 is 3%)';
const RATIO = 'decimal ratio (0.05 is 5%)';

/** The shape `GET /scenario-targets` returns for the P7.1 registry. */
const CATALOG: ScenarioTargetCatalog = {
  quick: [
    { target: 'exit_cap_rate', allowed_operations: ['set', 'add', 'scale'], units: RATE },
    { target: 'interest_rate', allowed_operations: ['set', 'add', 'scale'], units: RATE },
    { target: 'ltv', allowed_operations: ['cap_at'], units: 'decimal ratio (0.55 is 55%)' },
    { target: 'noi_growth', allowed_operations: ['set', 'add'], units: GROWTH },
  ],
  detailed: [
    { target: 'exit_cap_rate', allowed_operations: ['set', 'add', 'scale'], units: RATE },
    { target: 'interest_rate', allowed_operations: ['set', 'add', 'scale'], units: RATE },
    { target: 'ltv', allowed_operations: ['cap_at'], units: 'decimal ratio (0.55 is 55%)' },
    { target: 'revenue_growth', allowed_operations: ['set', 'add'], units: GROWTH },
    { target: 'vacancy_credit_loss_pct', allowed_operations: ['set', 'add'], units: RATIO },
    { target: 'expense_growth', allowed_operations: ['set', 'add'], units: GROWTH },
  ],
  lease_level: [
    { target: 'exit_cap_rate', allowed_operations: ['set', 'add', 'scale'], units: RATE },
    { target: 'interest_rate', allowed_operations: ['set', 'add', 'scale'], units: RATE },
    { target: 'ltv', allowed_operations: ['cap_at'], units: 'decimal ratio (0.55 is 55%)' },
    { target: 'expense_growth', allowed_operations: ['set', 'add'], units: GROWTH },
    {
      target: 'market_rent_psf',
      allowed_operations: ['set', 'add', 'scale', 'cap_at'],
      units: '$/SF/year as of analysis_start_date',
    },
    {
      target: 'renewal_probability',
      allowed_operations: ['set', 'add', 'scale', 'cap_at'],
      units: 'probability (0.65 is 65%)',
    },
    { target: 'recoverable_expense_ratio', allowed_operations: ['set', 'add'], units: RATIO },
  ],
};

function override(target: string, operation: ScenarioOverride['operation'], value: number): ScenarioOverride {
  return { unit_id: 'deal-1', target, operation, value };
}

function scenario(
  id: string,
  name: string,
  overrides: ScenarioOverride[],
  description: string | null = null,
): InvestmentScenario {
  return {
    investment_id: 'inv-1',
    scenario: { scenario_id: id, name, description, overrides },
    created_at: '2026-09-13T00:00:00+00:00',
    updated_at: '2026-09-13T00:00:00+00:00',
  };
}

const DOWNSIDE = scenario(
  'sc-down',
  'Downside',
  [override('exit_cap_rate', 'add', 0.005), override('interest_rate', 'add', 0.01)],
  'Higher exit cap and debt cost',
);
const UPSIDE = scenario('sc-up', 'Upside', [override('noi_growth', 'set', 0.04)]);

function listed(scenarios: InvestmentScenario[]) {
  return {
    deal_id: 'deal-1',
    investment_id: scenarios.length === 0 ? null : 'inv-1',
    scenarios,
  };
}

function results(fields: Partial<AcquisitionResults> = {}): AcquisitionResults {
  return {
    levered_irr: 0.1423,
    levered_irr_status: 'defined',
    unlevered_irr: 0.0911,
    unlevered_irr_status: 'defined',
    equity_multiple: 1.85,
    total_profit: 12_345_678,
    exit_value: 98_765_432,
    min_dscr: 1.42,
    ...fields,
  } as AcquisitionResults;
}

const BASE_RESULTS = results();
const DOWNSIDE_RESULTS = results({
  levered_irr: 0.1102,
  unlevered_irr: 0.0801,
  equity_multiple: 1.52,
  total_profit: 7_000_000,
  exit_value: 88_000_000,
  min_dscr: 1.18,
});
const UPSIDE_RESULTS = results({
  levered_irr: 0.1734,
  unlevered_irr: 0.1012,
  equity_multiple: 2.11,
  total_profit: 18_250_000,
  exit_value: 109_500_000,
  min_dscr: 1.61,
});

function analysis(
  scenarioId: string,
  figures: AcquisitionResults,
  mode: OperatingMode = 'quick',
  cacheStatus: VariantCacheStatus = 'miss',
): ScenarioVariantAnalysis {
  const envelope =
    mode === 'quick' ? figures : ({ results: figures } as unknown as DetailedAcquisitionResults);
  return {
    investment_id: 'inv-1',
    scenario_id: scenarioId,
    unit_id: 'deal-1',
    operating_mode: mode,
    source_fingerprint: `fp-${scenarioId}`,
    cache_status: cacheStatus,
    results: envelope,
  };
}

const EMPTY_PLAN = { capital_items: [], owner_expense_items: [] };

function savedDeal(mode: OperatingMode = 'quick'): Deal {
  const base: Deal = {
    id: 'deal-1',
    name: '111 Main St',
    operating_mode: mode,
    inputs: null,
    terms: null,
    detailed_operating_inputs: null,
    property_inputs: null,
    operating_inputs: null,
    market_leasing: null,
    suites: null,
    leases: null,
    business_plan: EMPTY_PLAN,
    deal_context: null,
    analysis_snapshot: null,
    ai_snapshot: null,
    one_way_sensitivity_snapshot: null,
    two_way_sensitivity_snapshot: null,
    created_at: '2026-09-13T00:00:00+00:00',
    updated_at: 'saved-1',
  };
  const terms = { purchase_price: 30_000_000 } as AcquisitionTermsRequest;
  switch (mode) {
    case 'quick':
      return { ...base, inputs: { purchase_price: 50_000_000 } as AcquisitionRequest };
    case 'detailed':
      return {
        ...base,
        terms,
        detailed_operating_inputs: { gross_potential_rent: 800_000 } as DetailedOperatingInputsRequest,
      };
    case 'lease_level':
      return {
        ...base,
        terms,
        property_inputs: { analysis_start_date: '2027-01-01' } as never,
        operating_inputs: { expense_growth: 0.03 } as never,
        market_leasing: { market_rent_psf: 30 } as never,
        suites: [],
        leases: [],
      };
  }
}

function scenarioIssue(message: string, target: string | null): ScenarioIssue {
  return {
    stage: target === null ? 'scenario' : 'resolved_inputs',
    code: target === null ? 'invalid_scenario_name' : 'resolved_input_invalid',
    message,
    target,
    unit_id: 'deal-1',
    field: null,
    source_code: null,
  };
}

function refusal(issues: ScenarioIssue[]): ScenarioApiError {
  return new ScenarioApiError(issues.map((issue) => issue.message).join(' '), 422, {
    issues: [],
    scenarioIssues: issues,
    leaseIssues: [],
    reasons: issues.map((issue) => issue.message),
  });
}

const NETWORK = 'Could not reach the Anchor API. Confirm the backend is running at http://127.0.0.1:8000.';

// =============================================================================
// Driving the workspace
// =============================================================================

const DEFAULT_PROPS: ScenarioWorkspaceProps = {
  operatingMode: 'quick',
  dealId: 'deal-1',
  isDirty: false,
  savedAt: 'saved-1',
  isActive: true,
};

function renderWorkspace(props: Partial<ScenarioWorkspaceProps> = {}) {
  let current: ScenarioWorkspaceProps = { ...DEFAULT_PROPS, ...props };
  const view = render(<ScenarioWorkspace {...current} />);
  return {
    user: userEvent.setup(),
    rerenderWith(next: Partial<ScenarioWorkspaceProps>) {
      current = { ...current, ...next };
      view.rerender(<ScenarioWorkspace {...current} />);
    },
  };
}

function button(name: string): HTMLButtonElement {
  return screen.getByRole('button', { name }) as HTMLButtonElement;
}

async function readyToEdit() {
  await waitFor(() => expect(button('Add Scenario').disabled).toBe(false));
}

function assumption(index = 0): HTMLSelectElement {
  return screen.getAllByLabelText('Assumption')[index] as HTMLSelectElement;
}

function optionLabels(select: HTMLSelectElement): string[] {
  return Array.from(select.options).map((option) => option.textContent ?? '');
}

function matrix(): HTMLElement {
  return screen.getByRole('table', { name: /Headline results/ });
}

function figure(metric: string, column: string): HTMLElement {
  const row = within(matrix()).getByRole('rowheader', { name: metric }).closest('tr') as HTMLElement;
  const found = row.querySelector(`[data-column="${column}"]`);
  if (found === null) {
    throw new Error(`No ${column} cell in the ${metric} row`);
  }
  return found as HTMLElement;
}

function statusCell(column: string): HTMLElement {
  return figure('Levered IRR', column);
}

function comparisonSection(): HTMLElement {
  return screen.getByRole('region', { name: 'Scenario Comparison' });
}

async function runComparison(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: /(Run|Refresh) Comparison/ }));
  await screen.findByRole('button', { name: 'Refresh Comparison' });
  await waitFor(() => expect(button('Refresh Comparison').disabled).toBe(false));
}

function scenarioAnalyses(byId: Record<string, ScenarioVariantAnalysis | Error>) {
  mockAnalyzeScenario.mockImplementation(async (_investmentId, scenarioId) => {
    const outcome = byId[scenarioId];
    if (outcome instanceof Error) {
      throw outcome;
    }
    return outcome;
  });
}

beforeEach(() => {
  vi.resetAllMocks();
  mockList.mockResolvedValue(listed([]));
  mockCatalog.mockResolvedValue(CATALOG);
  mockGetDeal.mockResolvedValue(savedDeal('quick'));
  mockAnalyzeQuick.mockResolvedValue(BASE_RESULTS);
  scenarioAnalyses({
    'sc-down': analysis('sc-down', DOWNSIDE_RESULTS),
    'sc-up': analysis('sc-up', UPSIDE_RESULTS),
  });
});

afterEach(() => {
  cleanup();
});

// =============================================================================
// State: opt-in, unsaved, dirty, load
// =============================================================================

describe('opt-in and saved state', () => {
  it('shows a saved deal with no scenarios as one sentence and Add Scenario', async () => {
    renderWorkspace();
    await readyToEdit();

    expect(screen.getByRole('heading', { name: 'Scenarios' })).toBeTruthy();
    expect(
      screen.getByText('Create named Downside, Upside, or other views by overriding selected assumptions.'),
    ).toBeTruthy();
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Scenario Comparison' })).toBeNull();
    expect(screen.queryByText(/Investment/)).toBeNull();
    expect(mockList).toHaveBeenCalledTimes(1);
    expect(mockList).toHaveBeenCalledWith('deal-1');
    // Viewing creates nothing.
    expect(mockCreate).not.toHaveBeenCalled();
    expect(mockAnalyzeScenario).not.toHaveBeenCalled();
  });

  it('asks for a save first on an unsaved deal, and requests nothing', async () => {
    renderWorkspace({ dealId: null, savedAt: null });

    expect(screen.getByText('Save this deal before adding scenarios.')).toBeTruthy();
    expect(button('Add Scenario').disabled).toBe(true);
    await Promise.resolve();
    expect(mockList).not.toHaveBeenCalled();
    expect(mockCatalog).not.toHaveBeenCalled();
    expect(screen.queryByText('Loading scenarios…')).toBeNull();
  });

  it('requests nothing until the Risk workspace is on screen', async () => {
    const { rerenderWith } = renderWorkspace({ isActive: false });
    await Promise.resolve();
    expect(mockList).not.toHaveBeenCalled();

    rerenderWith({ isActive: true });
    await waitFor(() => expect(mockList).toHaveBeenCalledWith('deal-1'));
  });

  it('shows a dirty deal’s scenarios but blocks changing or running them', async () => {
    mockList.mockResolvedValue(listed([DOWNSIDE]));
    renderWorkspace({ isDirty: true });

    await screen.findByText('Downside');
    expect(screen.getByText(SAVE_BEFORE_SCENARIOS_MESSAGE)).toBeTruthy();
    expect(button('Add Scenario').disabled).toBe(true);
    expect(button('Edit Downside').disabled).toBe(true);
    expect(button('Delete Downside').disabled).toBe(true);
    const run = button('Run Comparison');
    expect(run.disabled).toBe(true);
    expect(run.getAttribute('aria-describedby')).toBe('scenario-blocked-reason');
  });

  it('lists each saved scenario with its description, override count and a readable summary', async () => {
    mockList.mockResolvedValue(listed([DOWNSIDE, UPSIDE]));
    renderWorkspace();

    const list = await screen.findByRole('list', { name: 'Saved scenarios' });
    const [down, up] = within(list).getAllByRole('listitem');
    expect(within(down).getByText('Downside')).toBeTruthy();
    expect(within(down).getByText('Higher exit cap and debt cost')).toBeTruthy();
    expect(within(down).getByText('2 overrides')).toBeTruthy();
    expect(
      within(down).getByText('Exit Cap Rate: Add +0.5% pts · Interest Rate: Add +1% pts'),
    ).toBeTruthy();
    expect(within(up).getByText('1 override')).toBeTruthy();
    expect(within(up).getByText('NOI Growth: Set To 4%')).toBeTruthy();
    // No internal identifier or enum token reaches the analyst.
    const text = document.body.textContent ?? '';
    for (const hidden of ['deal-1', 'inv-1', 'sc-down', 'exit_cap_rate', 'cap_at']) {
      expect(text).not.toContain(hidden);
    }
  });

  it('says why the scenarios could not be loaded, and retries', async () => {
    mockList.mockRejectedValueOnce(new ApiError(NETWORK));
    const { user } = renderWorkspace();

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Could not reach the Anchor API');
    mockList.mockResolvedValue(listed([DOWNSIDE]));
    await user.click(within(alert).getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Downside')).toBeTruthy();
  });
});

// =============================================================================
// Editor
// =============================================================================

describe('the Scenario editor', () => {
  it('creates the first scenario with a unit-addressed override on the wire scale', async () => {
    mockCreate.mockResolvedValue(
      scenario('sc-new', 'Downside', [override('exit_cap_rate', 'add', 0.005)], 'Higher exit cap'),
    );
    const { user } = renderWorkspace();
    await readyToEdit();

    await user.click(button('Add Scenario'));
    expect(button('Add Scenario').getAttribute('aria-expanded')).toBe('true');
    expect(document.activeElement).toBe(screen.getByLabelText('Scenario Name'));
    await user.type(screen.getByLabelText('Scenario Name'), 'Downside');
    await user.type(screen.getByLabelText('Description (optional)'), 'Higher exit cap');
    await user.selectOptions(assumption(), 'exit_cap_rate');
    await user.selectOptions(screen.getByLabelText('Operation for Exit Cap Rate'), 'add');
    await user.type(screen.getByLabelText('Value for Exit Cap Rate'), '0.5');
    await user.click(button('Save Scenario'));

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    expect(mockCreate).toHaveBeenCalledWith('deal-1', {
      name: 'Downside',
      description: 'Higher exit cap',
      overrides: [{ unit_id: 'deal-1', target: 'exit_cap_rate', operation: 'add', value: 0.005 }],
    });
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'New Scenario' })).toBeNull());
    expect(screen.getByText('Downside')).toBeTruthy();
    expect(button('Run Comparison')).toBeTruthy();
    expect(document.activeElement).toBe(button('Add Scenario'));
  });

  it('offers only the operating mode’s own targets', async () => {
    for (const [mode, expected] of [
      ['quick', ['Exit Cap Rate', 'Interest Rate', 'Maximum LTV', 'NOI Growth']],
      [
        'detailed',
        ['Exit Cap Rate', 'Interest Rate', 'Maximum LTV', 'Revenue Growth', 'Vacancy & Credit Loss', 'Expense Growth'],
      ],
      [
        'lease_level',
        [
          'Exit Cap Rate',
          'Interest Rate',
          'Maximum LTV',
          'Expense Growth',
          'Market Rent',
          'Renewal Probability',
          'Recoverable Expense Ratio',
        ],
      ],
    ] as [OperatingMode, string[]][]) {
      const { user } = renderWorkspace({ operatingMode: mode });
      await readyToEdit();
      await user.click(button('Add Scenario'));
      await waitFor(() => expect(assumption().options.length).toBeGreaterThan(1));
      expect(optionLabels(assumption()).slice(1)).toEqual(expected);
      cleanup();
    }
  });

  it('offers each assumption only its whitelisted operations', async () => {
    const { user } = renderWorkspace();
    await readyToEdit();
    await user.click(button('Add Scenario'));
    await waitFor(() => expect(assumption().options.length).toBeGreaterThan(1));

    await user.selectOptions(assumption(), 'ltv');
    const ltvOperation = screen.getByLabelText('Operation for Maximum LTV') as HTMLSelectElement;
    expect(optionLabels(ltvOperation)).toEqual(['Choose…', 'Cap At']);
    // The only operation on offer is chosen; the analyst still types the value.
    expect(ltvOperation.value).toBe('cap_at');

    await user.selectOptions(assumption(), 'exit_cap_rate');
    const exitOperation = screen.getByLabelText('Operation for Exit Cap Rate') as HTMLSelectElement;
    expect(optionLabels(exitOperation)).toEqual(['Choose…', 'Set To', 'Add', 'Scale']);
    expect(exitOperation.value).toBe('');
  });

  it('does not offer an assumption another row already uses', async () => {
    const { user } = renderWorkspace();
    await readyToEdit();
    await user.click(button('Add Scenario'));
    await waitFor(() => expect(assumption().options.length).toBeGreaterThan(1));
    await user.selectOptions(assumption(), 'exit_cap_rate');
    await user.click(button('Add Override'));

    expect(optionLabels(assumption(1))).not.toContain('Exit Cap Rate');
    expect(optionLabels(assumption(0))).toContain('Exit Cap Rate');
  });

  it('types rates as percentages, multipliers as multipliers and rents in $/SF/yr', async () => {
    mockCreate.mockResolvedValue(scenario('sc-new', 'Soft market', []));
    const { user } = renderWorkspace({ operatingMode: 'lease_level' });
    await readyToEdit();
    await user.click(button('Add Scenario'));
    await waitFor(() => expect(assumption().options.length).toBeGreaterThan(1));
    await user.type(screen.getByLabelText('Scenario Name'), 'Soft market');

    await user.selectOptions(assumption(0), 'market_rent_psf');
    await user.selectOptions(screen.getByLabelText('Operation for Market Rent'), 'set');
    await user.type(screen.getByLabelText('Value for Market Rent'), '32.5');
    const rentCell = screen.getByLabelText('Value for Market Rent').closest('td') as HTMLElement;
    expect(rentCell.textContent).toContain('$');
    expect(rentCell.textContent).toContain('/SF/yr');

    await user.click(button('Add Override'));
    await user.selectOptions(assumption(1), 'exit_cap_rate');
    await user.selectOptions(screen.getByLabelText('Operation for Exit Cap Rate'), 'scale');
    await user.type(screen.getByLabelText('Value for Exit Cap Rate'), '1.1');

    await user.click(button('Add Override'));
    await user.selectOptions(assumption(2), 'renewal_probability');
    await user.selectOptions(screen.getByLabelText('Operation for Renewal Probability'), 'set');
    await user.type(screen.getByLabelText('Value for Renewal Probability'), '70');

    await user.click(button('Save Scenario'));
    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    expect(mockCreate.mock.calls[0][1].overrides).toEqual([
      { unit_id: 'deal-1', target: 'market_rent_psf', operation: 'set', value: 32.5 },
      { unit_id: 'deal-1', target: 'exit_cap_rate', operation: 'scale', value: 1.1 },
      { unit_id: 'deal-1', target: 'renewal_probability', operation: 'set', value: 0.7 },
    ]);
  });

  it('says an ADD on a rate is in percentage points', async () => {
    const { user } = renderWorkspace();
    await readyToEdit();
    await user.click(button('Add Scenario'));
    await waitFor(() => expect(assumption().options.length).toBeGreaterThan(1));
    await user.selectOptions(assumption(), 'interest_rate');
    await user.selectOptions(screen.getByLabelText('Operation for Interest Rate'), 'add');

    const cell = screen.getByLabelText('Value for Interest Rate').closest('td') as HTMLElement;
    expect(cell.textContent).toContain('% pts');
    expect(cell.textContent).toMatch(/percentage points/i);
  });

  it('reports presence problems before anything is sent', async () => {
    const { user } = renderWorkspace();
    await readyToEdit();
    await user.click(button('Add Scenario'));
    await user.click(button('Save Scenario'));

    const alerts = screen.getAllByRole('alert');
    const text = alerts.map((alert) => alert.textContent).join(' ');
    expect(text).toContain('Enter a scenario name.');
    expect(text).toContain('Choose an assumption.');
    expect(mockCreate).not.toHaveBeenCalled();
  });

  it('shows a backend refusal in its own words, on the row it names, and keeps every value', async () => {
    const onRow = "exit_cap_rate: exit_cap_rate must be greater than 0.";
    const general = 'The saved base inputs have an issue no override owns.';
    mockCreate.mockRejectedValueOnce(
      refusal([scenarioIssue(onRow, 'exit_cap_rate'), scenarioIssue(general, null)]),
    );
    const { user } = renderWorkspace();
    await readyToEdit();
    await user.click(button('Add Scenario'));
    await waitFor(() => expect(assumption().options.length).toBeGreaterThan(1));
    await user.type(screen.getByLabelText('Scenario Name'), 'Deep Downside');
    await user.selectOptions(assumption(), 'exit_cap_rate');
    await user.selectOptions(screen.getByLabelText('Operation for Exit Cap Rate'), 'set');
    await user.type(screen.getByLabelText('Value for Exit Cap Rate'), '-1');
    await user.click(button('Save Scenario'));

    const value = screen.getByLabelText('Value for Exit Cap Rate') as HTMLInputElement;
    await waitFor(() => expect(value.getAttribute('aria-invalid')).toBe('true'));
    const rowIssues = document.getElementById(value.getAttribute('aria-describedby')!.split(' ')[1]);
    expect(rowIssues?.textContent).toBe(onRow);
    expect(screen.getByText(general)).toBeTruthy();
    expect(screen.getByText(/The scenario was not saved/)).toBeTruthy();
    expect((screen.getByLabelText('Scenario Name') as HTMLInputElement).value).toBe('Deep Downside');
    expect(value.value).toBe('-1');
    expect(screen.queryByRole('list', { name: 'Saved scenarios' })).toBeNull();
  });

  it('keeps the editor after a failed request and saves on a retry', async () => {
    mockCreate.mockRejectedValueOnce(new ApiError(NETWORK));
    mockCreate.mockResolvedValueOnce(scenario('sc-new', 'Upside', [override('noi_growth', 'set', 0.04)]));
    const { user } = renderWorkspace();
    await readyToEdit();
    await user.click(button('Add Scenario'));
    await waitFor(() => expect(assumption().options.length).toBeGreaterThan(1));
    await user.type(screen.getByLabelText('Scenario Name'), 'Upside');
    await user.selectOptions(assumption(), 'noi_growth');
    await user.selectOptions(screen.getByLabelText('Operation for NOI Growth'), 'set');
    await user.type(screen.getByLabelText('Value for NOI Growth'), '4');
    await user.click(button('Save Scenario'));

    expect(await screen.findByText(NETWORK)).toBeTruthy();
    expect((screen.getByLabelText('Scenario Name') as HTMLInputElement).value).toBe('Upside');
    expect((screen.getByLabelText('Value for NOI Growth') as HTMLInputElement).value).toBe('4');

    await user.click(button('Save Scenario'));
    await screen.findByRole('list', { name: 'Saved scenarios' });
    expect(mockCreate).toHaveBeenCalledTimes(2);
    expect(mockCreate.mock.calls[1][1].overrides).toEqual([
      { unit_id: 'deal-1', target: 'noi_growth', operation: 'set', value: 0.04 },
    ]);
  });

  it('edits a scenario from its saved overrides, shown in display units', async () => {
    mockList.mockResolvedValue(listed([DOWNSIDE]));
    mockUpdate.mockResolvedValue(DOWNSIDE);
    const { user } = renderWorkspace();
    await readyToEdit();

    await user.click(button('Edit Downside'));
    expect(screen.getByRole('heading', { name: 'Edit Scenario' })).toBeTruthy();
    expect((screen.getByLabelText('Scenario Name') as HTMLInputElement).value).toBe('Downside');
    expect((screen.getByLabelText('Value for Exit Cap Rate') as HTMLInputElement).value).toBe('0.5');
    const interest = screen.getByLabelText('Value for Interest Rate') as HTMLInputElement;
    expect(interest.value).toBe('1');
    await user.clear(interest);
    await user.type(interest, '1.5');
    await user.click(button('Save Scenario'));

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));
    expect(mockUpdate).toHaveBeenCalledWith('inv-1', 'sc-down', {
      name: 'Downside',
      description: 'Higher exit cap and debt cost',
      overrides: [
        { unit_id: 'deal-1', target: 'exit_cap_rate', operation: 'add', value: 0.005 },
        { unit_id: 'deal-1', target: 'interest_rate', operation: 'add', value: 0.015 },
      ],
    });
  });

  it('reports a target-catalog failure in the editor and blocks Add Override', async () => {
    mockCatalog.mockRejectedValue(new ApiError(NETWORK));
    const { user } = renderWorkspace();
    await readyToEdit();
    await user.click(button('Add Scenario'));

    expect(await screen.findByText(NETWORK)).toBeTruthy();
    expect(button('Add Override').disabled).toBe(true);
  });

  it('is operable from the keyboard, with a label on every control', async () => {
    const { user } = renderWorkspace();
    await readyToEdit();

    await user.tab();
    expect(document.activeElement).toBe(button('Add Scenario'));
    await user.keyboard('{Enter}');
    expect(document.activeElement).toBe(screen.getByLabelText('Scenario Name'));
    await user.tab();
    expect(document.activeElement).toBe(screen.getByLabelText('Description (optional)'));
    await user.tab();
    expect(document.activeElement).toBe(assumption());
    await waitFor(() => expect(assumption().options.length).toBeGreaterThan(1));
    await user.selectOptions(assumption(), 'exit_cap_rate');
    expect(screen.getByLabelText('Operation for Exit Cap Rate')).toBeTruthy();
    expect(screen.getByLabelText('Value for Exit Cap Rate')).toBeTruthy();
    expect(button('Remove Exit Cap Rate override')).toBeTruthy();
  });
});

// =============================================================================
// Deletion
// =============================================================================

describe('deleting a scenario', () => {
  it('asks for confirmation inline, and Cancel deletes nothing', async () => {
    mockList.mockResolvedValue(listed([DOWNSIDE, UPSIDE]));
    mockDelete.mockResolvedValue(undefined);
    const { user } = renderWorkspace();
    await readyToEdit();

    await user.click(button('Delete Downside'));
    const confirm = screen.getByRole('group', { name: 'Confirm deleting Downside' });
    expect(document.activeElement).toBe(within(confirm).getByRole('button', { name: 'Cancel' }));
    await user.click(within(confirm).getByRole('button', { name: 'Cancel' }));
    expect(mockDelete).not.toHaveBeenCalled();
    expect(screen.queryByRole('group', { name: 'Confirm deleting Downside' })).toBeNull();

    await user.click(button('Delete Downside'));
    await user.click(button('Delete Scenario'));
    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith('inv-1', 'sc-down'));
    await waitFor(() => expect(screen.queryByText('Downside')).toBeNull());
    expect(screen.getByText('Upside')).toBeTruthy();
  });

  it('returns the deal to the simple state when the last scenario is deleted', async () => {
    mockList.mockResolvedValue(listed([DOWNSIDE]));
    mockDelete.mockResolvedValue(undefined);
    const { user } = renderWorkspace();
    await readyToEdit();
    await runComparison(user);

    await user.click(button('Delete Downside'));
    await user.click(button('Delete Scenario'));

    await waitFor(() => expect(screen.queryByRole('list', { name: 'Saved scenarios' })).toBeNull());
    expect(screen.queryByRole('heading', { name: 'Scenario Comparison' })).toBeNull();
    expect(screen.queryByRole('table')).toBeNull();
    expect(button('Add Scenario').disabled).toBe(false);
  });

  it('keeps the scenario, and the confirmation, when a delete fails', async () => {
    mockList.mockResolvedValue(listed([DOWNSIDE]));
    mockDelete.mockRejectedValueOnce(new ApiError(NETWORK));
    const { user } = renderWorkspace();
    await readyToEdit();

    await user.click(button('Delete Downside'));
    await user.click(button('Delete Scenario'));

    expect((await screen.findByRole('alert')).textContent).toBe(NETWORK);
    expect(screen.getByText('Downside')).toBeTruthy();
    expect(button('Delete Scenario')).toBeTruthy();
  });
});

// =============================================================================
// The comparison
// =============================================================================

describe('the Scenario Comparison', () => {
  it('runs Base through the ordinary analysis and each scenario through the Scenario route', async () => {
    mockList.mockResolvedValue(listed([DOWNSIDE, UPSIDE]));
    const { user } = renderWorkspace();
    await readyToEdit();
    expect(screen.getByText('Run Comparison to analyze Base and every saved scenario side by side.')).toBeTruthy();

    await runComparison(user);

    const deal = savedDeal('quick');
    expect(mockGetDeal).toHaveBeenCalledWith('deal-1');
    expect(mockAnalyzeQuick).toHaveBeenCalledWith(deal.inputs, deal.business_plan);
    expect(mockAnalyzeScenario.mock.calls).toEqual([
      ['inv-1', 'sc-down'],
      ['inv-1', 'sc-up'],
    ]);
    expect(mockAnalyzeDetailed).not.toHaveBeenCalled();
    expect(mockAnalyzeLeaseLevel).not.toHaveBeenCalled();

    const table = matrix();
    expect(
      within(table)
        .getAllByRole('columnheader')
        .map((header) => header.textContent),
    ).toEqual(['Metric', 'Base', 'Downside', 'Upside']);
    expect(within(table).getAllByRole('rowheader').map((header) => header.textContent)).toEqual([
      'Current Underwriting',
      'Levered IRR',
      'Unlevered IRR',
      'Equity Multiple',
      'Total Profit',
      'Exit Value',
      'Minimum DSCR',
    ]);
  });

  it('shows each backend field formatted, and no figure derived across cells', async () => {
    mockList.mockResolvedValue(listed([DOWNSIDE, UPSIDE]));
    const { user } = renderWorkspace();
    await readyToEdit();
    await runComparison(user);

    const expected: Record<string, [string, string, string]> = {
      'Levered IRR': ['14.23%', '11.02%', '17.34%'],
      'Unlevered IRR': ['9.11%', '8.01%', '10.12%'],
      'Equity Multiple': ['1.85x', '1.52x', '2.11x'],
      'Total Profit': ['$12,345,678', '$7,000,000', '$18,250,000'],
      'Exit Value': ['$98,765,432', '$88,000,000', '$109,500,000'],
      'Minimum DSCR': ['1.42x', '1.18x', '1.61x'],
    };
    for (const [metric, [base, down, up]] of Object.entries(expected)) {
      expect(figure(metric, 'base').textContent).toBe(base);
      expect(figure(metric, 'sc-down').textContent).toBe(down);
      expect(figure(metric, 'sc-up').textContent).toBe(up);
    }
    expect(matrix().querySelectorAll('td.scenario-matrix-figure')).toHaveLength(18);

    const text = comparisonSection().textContent ?? '';
    // Base minus Downside, as a profit and as an IRR, never appears.
    expect(text).not.toContain('5,345,678');
    expect(text).not.toContain('3.21%');
    expect(text).not.toMatch(/\bvs\.? Base\b|Δ|Delta|Worst|Best|Range|Average|Difference|Expected/i);
  });

  it('shows an invalid scenario with its reasons and leaves the other columns standing', async () => {
    const reason = 'exit_cap_rate: exit_cap_rate must be greater than 0.';
    mockList.mockResolvedValue(listed([DOWNSIDE, UPSIDE]));
    scenarioAnalyses({
      'sc-down': refusal([scenarioIssue(reason, 'exit_cap_rate')]),
      'sc-up': analysis('sc-up', UPSIDE_RESULTS),
    });
    const { user } = renderWorkspace();
    await readyToEdit();
    await runComparison(user);

    const invalid = statusCell('sc-down');
    expect(invalid.textContent).toContain('Invalid variant');
    expect(invalid.textContent).toContain(reason);
    expect(figure('Levered IRR', 'base').textContent).toBe('14.23%');
    expect(figure('Levered IRR', 'sc-up').textContent).toBe('17.34%');
    expect(figure('Minimum DSCR', 'sc-up').textContent).toBe('1.61x');
  });

  it('shows an unreported IRR as N/A with the engine’s reason, and never as zero', async () => {
    mockList.mockResolvedValue(listed([DOWNSIDE, UPSIDE]));
    scenarioAnalyses({
      'sc-down': analysis('sc-down', DOWNSIDE_RESULTS),
      'sc-up': analysis(
        'sc-up',
        results({
          levered_irr: null,
          levered_irr_status: 'no_positive_cash_flow',
          equity_multiple: null,
          min_dscr: null,
          total_profit: 0,
        }),
      ),
    });
    const { user } = renderWorkspace();
    await readyToEdit();
    await runComparison(user);

    const irr = figure('Levered IRR', 'sc-up');
    const reason = 'Levered IRR is not reported because the modeled cash flows contain no positive cash flow.';
    expect(irr.textContent).toBe('N/A');
    expect(irr.getAttribute('title')).toBe(reason);
    const note = document.getElementById(irr.getAttribute('aria-describedby')!);
    expect(note?.textContent).toContain(`Upside: ${reason}`);
    expect(figure('Equity Multiple', 'sc-up').textContent).toBe('N/A');
    expect(figure('Minimum DSCR', 'sc-up').textContent).toBe('N/A');
    // A real zero is a figure, not a missing value.
    expect(figure('Total Profit', 'sc-up').textContent).toBe('$0');
    const text = comparisonSection().textContent ?? '';
    expect(text).not.toContain('0.00%');
    expect(text).not.toContain('0.00x');
  });

  it('keeps every other column when one request fails, and retries only that column', async () => {
    mockList.mockResolvedValue(listed([DOWNSIDE, UPSIDE]));
    scenarioAnalyses({
      'sc-down': analysis('sc-down', DOWNSIDE_RESULTS),
      'sc-up': new ApiError(NETWORK),
    });
    const { user } = renderWorkspace();
    await readyToEdit();
    await runComparison(user);

    const failed = statusCell('sc-up');
    expect(failed.textContent).toContain('Analysis failed');
    expect(failed.textContent).toContain(NETWORK);
    expect(figure('Levered IRR', 'sc-down').textContent).toBe('11.02%');

    scenarioAnalyses({ 'sc-up': analysis('sc-up', UPSIDE_RESULTS) });
    await user.click(button('Retry Upside'));
    await waitFor(() => expect(figure('Levered IRR', 'sc-up').textContent).toBe('17.34%'));
    expect(mockAnalyzeScenario.mock.calls.slice(2)).toEqual([['inv-1', 'sc-up']]);
    expect(mockGetDeal).toHaveBeenCalledTimes(1);
  });

  it('reports a Base failure in the Base column alone', async () => {
    mockList.mockResolvedValue(listed([DOWNSIDE]));
    mockGetDeal.mockRejectedValueOnce(new ApiError('That deal could not be found. It may have been deleted.'));
    const { user } = renderWorkspace();
    await readyToEdit();
    await runComparison(user);

    expect(statusCell('base').textContent).toContain('Base analysis failed');
    expect(statusCell('base').textContent).toContain('That deal could not be found.');
    expect(figure('Levered IRR', 'sc-down').textContent).toBe('11.02%');
  });

  it('reruns every column on Refresh Comparison', async () => {
    mockList.mockResolvedValue(listed([DOWNSIDE, UPSIDE]));
    const { user } = renderWorkspace();
    await readyToEdit();
    await runComparison(user);
    await runComparison(user);

    expect(mockGetDeal).toHaveBeenCalledTimes(2);
    expect(mockAnalyzeScenario).toHaveBeenCalledTimes(4);
  });

  it('is a table inside its own scrolling region', async () => {
    mockList.mockResolvedValue(listed([DOWNSIDE]));
    const { user } = renderWorkspace();
    await readyToEdit();
    await runComparison(user);

    const region = screen.getByRole('region', { name: 'Scenario comparison table' });
    expect(region.classList.contains('scenario-matrix-scroll')).toBe(true);
    expect(region.tabIndex).toBe(0);
    expect(within(region).getByRole('table')).toBe(matrix());
    expect(within(matrix()).getByRole('rowheader', { name: 'Current Underwriting' })).toBeTruthy();
  });
});

describe('out of date is never shown as current', () => {
  async function ranComparison() {
    mockList.mockResolvedValue(listed([DOWNSIDE, UPSIDE]));
    const rendered = renderWorkspace();
    await readyToEdit();
    await runComparison(rendered.user);
    return rendered;
  }

  it('marks the comparison out of date after a new save, until it is refreshed', async () => {
    const { user, rerenderWith } = await ranComparison();

    rerenderWith({ savedAt: 'saved-2' });
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.getByText('Out of date')).toBeTruthy();
    expect(screen.getByText(STALE_COMPARISON_MESSAGE)).toBeTruthy();
    expect(button('Refresh Comparison').disabled).toBe(false);

    await runComparison(user);
    expect(matrix()).toBeTruthy();
  });

  it('hides the comparison and blocks a refresh while the base is dirty', async () => {
    const { rerenderWith } = await ranComparison();
    const requests = mockAnalyzeScenario.mock.calls.length;

    rerenderWith({ isDirty: true });
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.getByText(DIRTY_COMPARISON_MESSAGE)).toBeTruthy();
    expect(button('Refresh Comparison').disabled).toBe(true);

    // Reverting the unsaved edit restores exactly the saved state that ran.
    rerenderWith({ isDirty: false });
    expect(matrix()).toBeTruthy();
    expect(mockAnalyzeScenario.mock.calls.length).toBe(requests);
  });

  it('marks the comparison out of date when a scenario’s overrides change', async () => {
    const { user } = await ranComparison();
    mockUpdate.mockResolvedValue(
      scenario(
        'sc-down',
        'Downside',
        [override('exit_cap_rate', 'add', 0.0075), override('interest_rate', 'add', 0.01)],
        'Higher exit cap and debt cost',
      ),
    );

    await user.click(button('Edit Downside'));
    const exit = screen.getByLabelText('Value for Exit Cap Rate');
    await user.clear(exit);
    await user.type(exit, '0.75');
    await user.click(button('Save Scenario'));

    await screen.findByText(STALE_COMPARISON_MESSAGE);
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('relabels a renamed scenario’s column at once, without a re-run', async () => {
    const { user } = await ranComparison();
    const requests = mockAnalyzeScenario.mock.calls.length;
    mockUpdate.mockResolvedValue({
      ...DOWNSIDE,
      scenario: { ...DOWNSIDE.scenario, name: 'Severe Downside' },
    });

    await user.click(button('Edit Downside'));
    const name = screen.getByLabelText('Scenario Name');
    await user.clear(name);
    await user.type(name, 'Severe Downside');
    await user.click(button('Save Scenario'));

    await waitFor(() =>
      expect(within(matrix()).getByRole('columnheader', { name: 'Severe Downside' })).toBeTruthy(),
    );
    expect(figure('Levered IRR', 'sc-down').textContent).toBe('11.02%');
    expect(mockAnalyzeScenario.mock.calls.length).toBe(requests);
  });

  it('marks the comparison out of date when a scenario is added', async () => {
    const { user } = await ranComparison();
    mockCreate.mockResolvedValue(scenario('sc-rates', 'Rate shock', [override('interest_rate', 'add', 0.02)]));

    await user.click(button('Add Scenario'));
    await waitFor(() => expect(assumption().options.length).toBeGreaterThan(1));
    await user.type(screen.getByLabelText('Scenario Name'), 'Rate shock');
    await user.selectOptions(assumption(), 'interest_rate');
    await user.selectOptions(screen.getByLabelText('Operation for Interest Rate'), 'add');
    await user.type(screen.getByLabelText('Value for Interest Rate'), '2');
    await user.click(button('Save Scenario'));

    await screen.findByText(STALE_COMPARISON_MESSAGE);
  });
});

describe('every operating mode', () => {
  it('runs a Detailed Base through the Detailed analysis and reads its envelope', async () => {
    const deal = savedDeal('detailed');
    mockGetDeal.mockResolvedValue(deal);
    mockAnalyzeDetailed.mockResolvedValue({ results: BASE_RESULTS } as unknown as DetailedAcquisitionResults);
    mockList.mockResolvedValue(listed([DOWNSIDE]));
    scenarioAnalyses({ 'sc-down': analysis('sc-down', DOWNSIDE_RESULTS, 'detailed', 'hit') });
    const { user } = renderWorkspace({ operatingMode: 'detailed' });
    await readyToEdit();
    await runComparison(user);

    expect(mockAnalyzeDetailed).toHaveBeenCalledWith(
      deal.terms,
      deal.detailed_operating_inputs,
      deal.business_plan,
    );
    expect(mockAnalyzeQuick).not.toHaveBeenCalled();
    expect(figure('Levered IRR', 'base').textContent).toBe('14.23%');
    expect(figure('Levered IRR', 'sc-down').textContent).toBe('11.02%');
  });

  it('runs a Lease-Level Base through the Lease-Level analysis, and never shows the cache', async () => {
    const deal = savedDeal('lease_level');
    mockGetDeal.mockResolvedValue(deal);
    mockAnalyzeLeaseLevel.mockResolvedValue({ results: BASE_RESULTS } as unknown as LeaseLevelAcquisitionResults);
    mockList.mockResolvedValue(listed([DOWNSIDE]));
    scenarioAnalyses({ 'sc-down': analysis('sc-down', DOWNSIDE_RESULTS, 'lease_level', 'bypassed') });
    const { user } = renderWorkspace({ operatingMode: 'lease_level' });
    await readyToEdit();
    await runComparison(user);

    expect(mockAnalyzeLeaseLevel).toHaveBeenCalledWith(
      deal.terms,
      {
        property_inputs: deal.property_inputs,
        operating_inputs: deal.operating_inputs,
        market_leasing: deal.market_leasing,
        suites: deal.suites,
        leases: deal.leases,
      },
      deal.business_plan,
    );
    expect(figure('Exit Value', 'sc-down').textContent).toBe('$88,000,000');
    const header = within(matrix()).getByRole('columnheader', { name: 'Downside' });
    expect(header.getAttribute('data-cache-status')).toBe('bypassed');
    expect(screen.queryByText(/bypassed|cache/i)).toBeNull();
  });
});
