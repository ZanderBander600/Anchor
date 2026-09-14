/**
 * Phase 7 Gate P7.3 -- the Scenario workspace: state and editor.
 *
 * Drives `ScenarioWorkspace` over `useScenarios` against a mocked `api.ts`. The
 * error classes stay real, so a refusal reaches the hook exactly as the client
 * would raise it.
 *
 * P7.5 moved comparison to the Strategy x Scenario Decision Matrix, the one
 * comparison surface (`decisionMatrix.test.tsx`), so this file proves the
 * Scenario manager and editor alone.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  ApiError,
  createDealScenario,
  deleteInvestmentScenario,
  fetchScenarioTargetCatalog,
  listDealScenarios,
  ScenarioApiError,
  updateInvestmentScenario,
} from './api';
import { ScenarioWorkspace } from './components/ScenarioWorkspace';
import { SAVE_BEFORE_SCENARIOS_MESSAGE, useScenarios } from './useScenarios';
import type { UseScenariosOptions } from './useScenarios';
import type {
  InvestmentScenario,
  ScenarioIssue,
  ScenarioOverride,
  ScenarioTargetCatalog,
} from './scenarioTypes';
import type { OperatingMode } from './types';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    createDealScenario: vi.fn(),
    deleteInvestmentScenario: vi.fn(),
    fetchScenarioTargetCatalog: vi.fn(),
    listDealScenarios: vi.fn(),
    updateInvestmentScenario: vi.fn(),
  };
});

const mockList = vi.mocked(listDealScenarios);
const mockCatalog = vi.mocked(fetchScenarioTargetCatalog);
const mockCreate = vi.mocked(createDealScenario);
const mockUpdate = vi.mocked(updateInvestmentScenario);
const mockDelete = vi.mocked(deleteInvestmentScenario);

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

/** The workspace as `RiskDecisionWorkspace` mounts it: the hook's state,
 * rendered. */
function Harness(props: UseScenariosOptions) {
  return <ScenarioWorkspace state={useScenarios(props)} />;
}

const DEFAULT_PROPS: UseScenariosOptions = {
  operatingMode: 'quick',
  dealId: 'deal-1',
  isDirty: false,
  isActive: true,
};

function renderWorkspace(props: Partial<UseScenariosOptions> = {}) {
  let current: UseScenariosOptions = { ...DEFAULT_PROPS, ...props };
  const view = render(<Harness {...current} />);
  return {
    user: userEvent.setup(),
    rerenderWith(next: Partial<UseScenariosOptions>) {
      current = { ...current, ...next };
      view.rerender(<Harness {...current} />);
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

beforeEach(() => {
  vi.resetAllMocks();
  mockList.mockResolvedValue(listed([]));
  mockCatalog.mockResolvedValue(CATALOG);
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
      screen.getByText(
        'Create named Downside, Upside, or other views by overriding selected assumptions. Compare them in the Decision Matrix.',
      ),
    ).toBeTruthy();
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Scenario Comparison' })).toBeNull();
    expect(screen.queryByText(/Investment/)).toBeNull();
    expect(mockList).toHaveBeenCalledTimes(1);
    expect(mockList).toHaveBeenCalledWith('deal-1');
    // Viewing creates nothing.
    expect(mockCreate).not.toHaveBeenCalled();
  });

  it('asks for a save first on an unsaved deal, and requests nothing', async () => {
    renderWorkspace({ dealId: null });

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

  it('shows a dirty deal’s scenarios but blocks changing them', async () => {
    mockList.mockResolvedValue(listed([DOWNSIDE]));
    renderWorkspace({ isDirty: true });

    await screen.findByText('Downside');
    expect(screen.getByText(SAVE_BEFORE_SCENARIOS_MESSAGE)).toBeTruthy();
    expect(button('Add Scenario').disabled).toBe(true);
    expect(button('Edit Downside').disabled).toBe(true);
    expect(button('Delete Downside').disabled).toBe(true);
    expect(button('Add Scenario').getAttribute('aria-describedby')).toBe('scenario-blocked-reason');
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


describe('a dirty base locks an editor that is already open', () => {
  /** Every control that could change the draft, plus Cancel. */
  function editorControls() {
    return {
      name: screen.getByLabelText('Scenario Name') as HTMLInputElement,
      description: screen.getByLabelText('Description (optional)') as HTMLInputElement,
      targets: screen.getAllByLabelText('Assumption') as HTMLSelectElement[],
      operations: screen.getAllByLabelText(/^Operation for /) as HTMLSelectElement[],
      values: screen.getAllByLabelText(/^Value for /) as HTMLInputElement[],
      removes: screen.getAllByRole('button', { name: /^Remove .* override$/ }) as HTMLButtonElement[],
      addOverride: button('Add Override'),
      save: button('Save Scenario'),
      cancel: button('Cancel'),
    };
  }

  function expectEditable(editable: boolean) {
    const controls = editorControls();
    const mutating = [
      controls.name,
      controls.description,
      ...controls.targets,
      ...controls.operations,
      ...controls.values,
      ...controls.removes,
      controls.addOverride,
      controls.save,
    ];
    // Name, description, Add Override, Save, and four controls per row.
    expect(mutating.length).toBeGreaterThanOrEqual(8);
    for (const control of mutating) {
      expect(control.disabled, control.id || control.getAttribute('aria-label') || control.textContent).toBe(
        !editable,
      );
    }
    // Leaving the editor is always possible.
    expect(controls.cancel.disabled).toBe(false);
  }

  function draftOnScreen() {
    const controls = editorControls();
    return {
      name: controls.name.value,
      description: controls.description.value,
      targets: controls.targets.map((select) => select.value),
      operations: controls.operations.map((select) => select.value),
      values: controls.values.map((input) => input.value),
    };
  }

  it('keeps an open Scenario’s draft on screen and locked, then editable again once the Deal is clean', async () => {
    mockList.mockResolvedValue(listed([DOWNSIDE]));
    mockUpdate.mockResolvedValue({
      ...DOWNSIDE,
      scenario: { ...DOWNSIDE.scenario, name: 'Downside revised' },
    });
    const { user, rerenderWith } = renderWorkspace();
    await readyToEdit();

    // 1. Open an existing Scenario while the Deal is clean, and change it.
    await user.click(button('Edit Downside'));
    await waitFor(() => expect(assumption().options.length).toBeGreaterThan(2));
    await user.clear(screen.getByLabelText('Scenario Name'));
    await user.type(screen.getByLabelText('Scenario Name'), 'Downside revised');
    await user.clear(screen.getByLabelText('Value for Interest Rate'));
    await user.type(screen.getByLabelText('Value for Interest Rate'), '1.5');
    expectEditable(true);
    const draft = {
      name: 'Downside revised',
      description: 'Higher exit cap and debt cost',
      targets: ['exit_cap_rate', 'interest_rate'],
      operations: ['add', 'add'],
      values: ['0.5', '1.5'],
    };
    expect(draftOnScreen()).toEqual(draft);

    // 2-12. The base becomes dirty while the editor stays mounted.
    rerenderWith({ isDirty: true });
    expect(screen.getByRole('heading', { name: 'Edit Scenario' })).toBeTruthy();
    expect(screen.getByText(SAVE_BEFORE_SCENARIOS_MESSAGE)).toBeTruthy();
    expectEditable(false);

    // 13. The draft is kept exactly as typed, and cannot be changed.
    expect(draftOnScreen()).toEqual(draft);
    await user.type(screen.getByLabelText('Scenario Name'), ' again');
    await user.type(screen.getByLabelText('Value for Exit Cap Rate'), '9');
    expect(draftOnScreen()).toEqual(draft);
    expect(mockUpdate).not.toHaveBeenCalled();

    // 14. Clean again: editable, with nothing lost.
    rerenderWith({ isDirty: false });
    expectEditable(true);
    expect(draftOnScreen()).toEqual(draft);
    await user.clear(screen.getByLabelText('Value for Interest Rate'));
    await user.type(screen.getByLabelText('Value for Interest Rate'), '2');
    await user.click(button('Save Scenario'));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));
    expect(mockUpdate).toHaveBeenCalledWith('inv-1', 'sc-down', {
      name: 'Downside revised',
      description: 'Higher exit cap and debt cost',
      overrides: [
        { unit_id: 'deal-1', target: 'exit_cap_rate', operation: 'add', value: 0.005 },
        { unit_id: 'deal-1', target: 'interest_rate', operation: 'add', value: 0.02 },
      ],
    });
  });

  it('locks a new Scenario’s draft the same way, and Cancel still leaves', async () => {
    const { user, rerenderWith } = renderWorkspace();
    await readyToEdit();
    await user.click(button('Add Scenario'));
    await waitFor(() => expect(assumption().options.length).toBeGreaterThan(1));
    await user.type(screen.getByLabelText('Scenario Name'), 'Rate shock');
    await user.type(screen.getByLabelText('Description (optional)'), 'Debt reprices');
    await user.selectOptions(assumption(), 'interest_rate');
    await user.selectOptions(screen.getByLabelText('Operation for Interest Rate'), 'add');
    await user.type(screen.getByLabelText('Value for Interest Rate'), '2');
    const draft = {
      name: 'Rate shock',
      description: 'Debt reprices',
      targets: ['interest_rate'],
      operations: ['add'],
      values: ['2'],
    };

    rerenderWith({ isDirty: true });
    expect(screen.getByRole('heading', { name: 'New Scenario' })).toBeTruthy();
    expectEditable(false);
    expect(draftOnScreen()).toEqual(draft);

    rerenderWith({ isDirty: false });
    expectEditable(true);
    expect(draftOnScreen()).toEqual(draft);

    rerenderWith({ isDirty: true });
    await user.click(button('Cancel'));
    expect(screen.queryByRole('heading', { name: 'New Scenario' })).toBeNull();
    expect(mockCreate).not.toHaveBeenCalled();
  });
});
