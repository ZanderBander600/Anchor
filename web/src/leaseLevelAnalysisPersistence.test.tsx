/**
 * D5.8A -- a completed analytical result belongs to the Deal that produced it.
 *
 * Human review reported two product-state defects, both of the same shape: the
 * AI report and the sensitivity runs disappeared when the analyst opened
 * another deal and came back. Navigation is not an underwriting change, so
 * neither should have.
 *
 * **The fake backend here is a store, not a stub.** `getDeal` reads from a map
 * that the snapshot-write mocks are the only thing that fill. So a report can
 * only be restored if the app genuinely *saved* it -- an implementation that
 * kept it in React state, or in a module-level variable, or in `localStorage`,
 * fails every restore test below rather than passing them by accident. That is
 * the whole point: this file distinguishes persistence from memory.
 *
 * **A refresh is a fresh render.** Unmounting `App` and rendering it again
 * destroys every piece of component state, every hook, every closure -- exactly
 * what a browser reload does to the tab. Only the store survives.
 *
 * **Nothing is restored by re-running it.** Every restore test asserts that
 * `analyze`, the AI call and both sensitivity runners were not called. We are
 * saving work, not silently recomputing it.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import { AiAnalystPanel } from './components/AiAnalystPanel';
import {
  ApiError,
  analyzeLeaseLevelAcquisition,
  fetchLeaseLevelAIAnalysis,
  fetchLeaseLevelDealFingerprint,
  getDeal,
  listDeals,
  runLeaseLevelOneWaySensitivity,
  runLeaseLevelTwoWaySensitivity,
  updateDealAiSnapshot,
  updateDealOneWaySensitivitySnapshot,
  updateDealTwoWaySensitivitySnapshot,
  updateLeaseLevelDeal,
} from './api';
import appSource from './App.tsx?raw';
import fixture from './leaseLevelResultsFixture.json';
import {
  ANALYSIS,
  ONE_WAY_RESULT,
  TWO_WAY_RESULT,
  clone,
  makeDeal,
} from './leaseLevelDealFixture';
import type { LeaseLevelAcquisitionResults } from './leaseLevelTypes';
import type {
  LeaseLevelOneWaySensitivitySnapshot,
  LeaseLevelTwoWaySensitivitySnapshot,
} from './leaseLevelSensitivityTypes';
import type { AIAnalysis, Deal } from './types';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    analyzeLeaseLevelAcquisition: vi.fn(),
    fetchLeaseLevelAIAnalysis: vi.fn(),
    fetchLeaseLevelDealFingerprint: vi.fn(),
    getDeal: vi.fn(),
    listDeals: vi.fn(),
    runLeaseLevelOneWaySensitivity: vi.fn(),
    runLeaseLevelTwoWaySensitivity: vi.fn(),
    updateDealAiSnapshot: vi.fn(),
    updateDealOneWaySensitivitySnapshot: vi.fn(),
    updateDealTwoWaySensitivitySnapshot: vi.fn(),
    updateLeaseLevelDeal: vi.fn(),
  };
});

/**
 * These tests drive the real `App` through whole analyst workflows -- open a
 * deal, analyze, generate, run two sensitivities, switch deal, come back -- so
 * one of them performs more work than an ordinary unit test does in a whole
 * file. The suite's 5s default is a fine bound for a component test and too
 * tight for these, particularly when the runner is executing forty files in
 * parallel. Raised here, for this file only; every other file keeps the default.
 *
 * This buys time, never leniency: nothing below waits on a timer, every
 * assertion is on state the app has actually reached, and a genuine hang still
 * fails.
 */
vi.setConfig({ testTimeout: 30_000, hookTimeout: 30_000 });

const mockAnalyze = vi.mocked(analyzeLeaseLevelAcquisition);
const mockAi = vi.mocked(fetchLeaseLevelAIAnalysis);
const mockFingerprint = vi.mocked(fetchLeaseLevelDealFingerprint);
const mockGetDeal = vi.mocked(getDeal);
const mockListDeals = vi.mocked(listDeals);
const mockOneWay = vi.mocked(runLeaseLevelOneWaySensitivity);
const mockTwoWay = vi.mocked(runLeaseLevelTwoWaySensitivity);
const mockSaveAi = vi.mocked(updateDealAiSnapshot);
const mockSaveOneWay = vi.mocked(updateDealOneWaySensitivitySnapshot);
const mockSaveTwoWay = vi.mocked(updateDealTwoWaySensitivitySnapshot);
const mockUpdateDeal = vi.mocked(updateLeaseLevelDeal);

const HEALTHY = fixture.healthy as unknown as LeaseLevelAcquisitionResults;

/**
 * The durable side of the world.
 *
 * `getDeal` serves from here and the three snapshot writers are the only things
 * that put anything in it. Deep-cloned on the way out so nothing the app is
 * handed can be mutated back into "storage" by reference -- which would let a
 * purely in-memory implementation appear to persist.
 */
const stored = new Map<string, Deal>();

function put(deal: Deal): void {
  stored.set(deal.id, clone(deal));
}

function patch(id: string, change: Partial<Deal>): Deal {
  const current = stored.get(id);
  if (current === undefined) {
    throw new Error(`No stored deal ${id}`);
  }
  const next = { ...current, ...change } as Deal;
  stored.set(id, clone(next));
  return clone(next);
}

beforeEach(() => {
  vi.clearAllMocks();
  stored.clear();
  put(makeDeal('deal-a', 'Deal A'));
  put(makeDeal('deal-b', 'Deal B'));

  mockAnalyze.mockResolvedValue(HEALTHY);
  mockAi.mockResolvedValue(ANALYSIS);
  mockOneWay.mockResolvedValue(ONE_WAY_RESULT);
  mockTwoWay.mockResolvedValue(TWO_WAY_RESULT);
  mockFingerprint.mockResolvedValue({
    financial_input_fingerprint: 'financial-fingerprint',
    ai_context_fingerprint: 'ai-fingerprint',
  });
  mockListDeals.mockImplementation(async () => [...stored.values()].map(clone));
  mockGetDeal.mockImplementation(async (id: string) => {
    const deal = stored.get(id);
    if (deal === undefined) {
      throw new ApiError(`No deal ${id}`);
    }
    return clone(deal);
  });
  mockSaveAi.mockImplementation(async (id: string, snapshot: AIAnalysis) =>
    patch(id, { ai_snapshot: clone(snapshot) }),
  );
  mockSaveOneWay.mockImplementation(
    async (id: string, snapshot: LeaseLevelOneWaySensitivitySnapshot) =>
      patch(id, { one_way_sensitivity_snapshot: clone(snapshot) }),
  );
  mockSaveTwoWay.mockImplementation(
    async (id: string, snapshot: LeaseLevelTwoWaySensitivitySnapshot) =>
      patch(id, { two_way_sensitivity_snapshot: clone(snapshot) }),
  );
  mockUpdateDeal.mockImplementation(async (id: string) => clone(stored.get(id)!));
});

afterEach(cleanup);

// =============================================================================
// Driving the app
// =============================================================================

type User = ReturnType<typeof userEvent.setup>;

/** Renders a brand-new app shell. Called a second time in a test, after
 * `cleanup()`, it *is* a browser refresh: nothing survives but the store.
 *
 * `delay: null` only removes `userEvent`'s artificial pause between
 * keystrokes. Every event is still dispatched, in order, exactly as it would be
 * -- the tests here type whole rent-roll figures into several candidate fields
 * per run, and the default delay alone put them past the suite's timeout. */
async function launch(): Promise<User> {
  const user = userEvent.setup({ delay: null });
  render(<App />);
  await screen.findByText('Deal A');
  return user;
}

/** Opens a saved deal from the sidebar's Recent Deals list.
 *
 * Scoped to the sidebar rather than the whole document: the Deal Library view
 * lists the same names, so an unscoped query would be ambiguous the moment a
 * test visited it. */
async function open(user: User, name: string): Promise<void> {
  const sidebar = document.querySelector('.sidebar-deal-list');
  if (sidebar === null) {
    throw new Error('No sidebar deal list');
  }
  await user.click(within(sidebar as HTMLElement).getByText(name));
  await waitFor(() => {
    expect(screen.getByDisplayValue(name)).toBeTruthy();
  });
}

function workspacePanel(id: string): HTMLElement {
  const element = document.getElementById(`workspace-panel-${id}`);
  if (element === null) {
    throw new Error(`No workspace panel ${id}`);
  }
  return element;
}

function sensitivityPanel(view: 'one-way' | 'two-way'): HTMLElement {
  const element = document.getElementById(`lease-level-sensitivity-panel-${view}`);
  if (element === null) {
    throw new Error(`No sensitivity panel ${view}`);
  }
  return element;
}

async function goTo(user: User, tab: string): Promise<void> {
  await user.click(screen.getByRole('tab', { name: tab }));
}

/** Opens the Risk workspace on one sensitivity view.
 *
 * Both panels stay mounted (the ARIA tab pattern), and the inactive one carries
 * `hidden` -- so it is out of the accessibility tree and a role query would not
 * find its table even when the table is there. Selecting the view first is what
 * makes "the table is on screen" the thing actually being asserted. */
async function showSensitivity(user: User, view: 'One-Way' | 'Two-Way'): Promise<HTMLElement> {
  await goTo(user, 'Risk');
  await user.click(screen.getByRole('tab', { name: view }));
  return sensitivityPanel(view === 'One-Way' ? 'one-way' : 'two-way');
}

async function analyze(user: User): Promise<void> {
  await user.click(screen.getByRole('button', { name: /^Analyz/i }));
  await waitFor(() => expect(mockAnalyze).toHaveBeenCalled());
}

async function generateAi(user: User): Promise<void> {
  await goTo(user, 'AI Analyst');
  await user.click(
    within(workspacePanel('ai')).getByRole('button', {
      name: /Generate AI Analysis|Regenerate Analysis/,
    }),
  );
  await waitFor(() =>
    expect(within(workspacePanel('ai')).queryByText(ANALYSIS.executive_summary)).not.toBeNull(),
  );
}

/** Adds candidate values to one editor, exactly as an analyst would. */
async function enterCandidates(
  user: User,
  scope: HTMLElement,
  legend: string,
  values: string[],
): Promise<void> {
  const addButtons = within(scope).getAllByRole('button', { name: 'Add Value' });
  const add = legend.startsWith('Column') ? addButtons[1] : addButtons[0];
  for (const value of values) {
    await user.click(add);
    const fields = within(scope).getAllByLabelText(new RegExp(`^${legend} \\d+$`));
    await user.type(fields[fields.length - 1], value);
  }
}

async function runOneWay(user: User): Promise<void> {
  await goTo(user, 'Risk');
  const scope = sensitivityPanel('one-way');
  await enterCandidates(user, scope, 'Exit Cap Rate candidate value', ['6', '6.5', '7']);
  await user.click(within(scope).getByRole('button', { name: 'Run Sensitivity' }));
  await waitFor(() => expect(mockOneWay).toHaveBeenCalled());
}

async function runTwoWay(user: User): Promise<void> {
  await goTo(user, 'Risk');
  await user.click(screen.getByRole('tab', { name: 'Two-Way' }));
  const scope = sensitivityPanel('two-way');
  await enterCandidates(user, scope, 'Row Exit Cap Rate candidate value', ['6', '6.5']);
  await enterCandidates(user, scope, 'Column Purchase Price candidate value', [
    '29000000',
    '30000000',
    '31000000',
  ]);
  await user.click(within(scope).getByRole('button', { name: 'Run Sensitivity' }));
  await waitFor(() => expect(mockTwoWay).toHaveBeenCalled());
}

/** The full workflow the gate describes: analyze, generate, run both. */
async function doTheWork(user: User): Promise<void> {
  await analyze(user);
  await generateAi(user);
  await runOneWay(user);
  await runTwoWay(user);
}

function candidateValues(scope: HTMLElement, legend: string): string[] {
  return within(scope)
    .queryAllByLabelText(new RegExp(`^${legend} \\d+$`))
    .map((field) => (field as HTMLInputElement).value);
}

function matrixRows(scope: HTMLElement): string[][] {
  const table = within(scope).getByRole('table');
  return Array.from(table.querySelectorAll('tbody tr')).map((row) =>
    Array.from(row.querySelectorAll('td')).map((cell) => cell.textContent ?? ''),
  );
}

function aiButtonLabel(): string {
  return (
    within(workspacePanel('ai'))
      .getAllByRole('button')
      .map((button) => button.textContent ?? '')
      .find((label) => /Generate AI Analysis|Regenerate Analysis/.test(label)) ?? ''
  );
}

function purchasePriceField(): HTMLInputElement {
  return document.getElementById('lease-level-terms-purchasePrice') as HTMLInputElement;
}

/** Edits Purchase Price and returns what it held before, so a test can put the
 * field back to *exactly* the saved value rather than to a re-typed
 * approximation of it. Display grouping means the two are not always the same
 * string, and "exactly" is the whole question a revert test is asking. */
async function editPurchasePrice(user: User, value: string): Promise<string> {
  await goTo(user, 'Underwrite');
  const field = purchasePriceField();
  const before = field.value;
  await user.clear(field);
  await user.type(field, value);
  return before;
}

// =============================================================================
// 1. The work is saved as it is completed
// =============================================================================

describe('completed analysis is written back to the deal', () => {
  it('saves the AI report, the one-way run and the two-way run, each on its own', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await doTheWork(user);

    await waitFor(() => expect(mockSaveAi).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mockSaveOneWay).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mockSaveTwoWay).toHaveBeenCalledTimes(1));

    expect(mockSaveAi.mock.calls[0][0]).toBe('deal-a');
    expect(mockSaveOneWay.mock.calls[0][0]).toBe('deal-a');
    expect(mockSaveTwoWay.mock.calls[0][0]).toBe('deal-a');
  });

  it('persists the configuration and the authoritative result as one snapshot', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await runOneWay(user);

    await waitFor(() => expect(mockSaveOneWay).toHaveBeenCalled());
    const [, snapshot] = mockSaveOneWay.mock.calls[0];
    expect(snapshot.configuration).toEqual({
      metric: 'levered_irr',
      assumption: 'exit_cap_rate',
      values: ['6', '6.5', '7'],
    });
    expect(snapshot.result).toEqual(ONE_WAY_RESULT);
  });

  it('carries the provenance fingerprint the backend will independently verify', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await runTwoWay(user);

    await waitFor(() => expect(mockSaveTwoWay).toHaveBeenCalled());
    expect(mockSaveTwoWay.mock.calls[0][2]).toBe('financial-fingerprint');
    expect(mockFingerprint).toHaveBeenCalled();
  });

  it('sends the AI report under the AI-context fingerprint, not the input one', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await generateAi(user);

    await waitFor(() => expect(mockSaveAi).toHaveBeenCalled());
    expect(mockSaveAi.mock.calls[0][2]).toBe('ai-fingerprint');
  });
});

// =============================================================================
// 2. Deal switching -- the reported defect
// =============================================================================

describe('switching deals', () => {
  it('5, 6, 21, 35: Deal A -> Deal B -> Deal A restores every result', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await doTheWork(user);
    await waitFor(() => expect(mockSaveTwoWay).toHaveBeenCalled());

    // Deal B: none of Deal A's work is anywhere on screen.
    await open(user, 'Deal B');
    await goTo(user, 'AI Analyst');
    expect(within(workspacePanel('ai')).queryByText(ANALYSIS.executive_summary)).toBeNull();
    await goTo(user, 'Risk');
    expect(within(sensitivityPanel('one-way')).queryByRole('table')).toBeNull();
    await user.click(screen.getByRole('tab', { name: 'Two-Way' }));
    expect(within(sensitivityPanel('two-way')).queryByRole('table')).toBeNull();

    // Back to Deal A: everything is where it was left.
    const analysesBefore = mockAnalyze.mock.calls.length;
    await open(user, 'Deal A');

    await goTo(user, 'AI Analyst');
    expect(
      await within(workspacePanel('ai')).findByText(ANALYSIS.executive_summary),
    ).toBeTruthy();

    await goTo(user, 'Risk');
    expect(within(sensitivityPanel('one-way')).getByRole('table')).toBeTruthy();
    await user.click(screen.getByRole('tab', { name: 'Two-Way' }));
    expect(within(sensitivityPanel('two-way')).getByRole('table')).toBeTruthy();

    //
    // NO FAKE RESTORE: nothing was recomputed to put any of that on screen.
    expect(mockAnalyze.mock.calls.length).toBe(analysesBefore);
    expect(mockAi).toHaveBeenCalledTimes(1);
    expect(mockOneWay).toHaveBeenCalledTimes(1);
    expect(mockTwoWay).toHaveBeenCalledTimes(1);
  });

  it('M4: a second deal never inherits the first deal’s analysis', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await doTheWork(user);
    await waitFor(() => expect(mockSaveTwoWay).toHaveBeenCalled());

    await open(user, 'Deal B');

    // Deal B has no stored analysis, so its AI workspace is the empty state --
    // not Deal A's report, and not a blank panel that used to hold one.
    await goTo(user, 'AI Analyst');
    expect(
      within(workspacePanel('ai')).getByText(/Analyze the deal first/i),
    ).toBeTruthy();
    expect(stored.get('deal-b')?.ai_snapshot).toBeNull();
  });

  it('restores the candidate editor exactly as it was submitted', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await runOneWay(user);
    await waitFor(() => expect(mockSaveOneWay).toHaveBeenCalled());

    await open(user, 'Deal B');
    await open(user, 'Deal A');
    await goTo(user, 'Risk');

    // 17, 18, 19, 23: metric, target, values and their order.
    expect(
      (document.getElementById('lease-level-one-way-metric') as HTMLSelectElement).value,
    ).toBe('levered_irr');
    expect(
      (document.getElementById('lease-level-one-way-assumption') as HTMLSelectElement).value,
    ).toBe('exit_cap_rate');
    expect(
      candidateValues(sensitivityPanel('one-way'), 'Exit Cap Rate candidate value'),
    ).toEqual(['6', '6.5', '7']);
  });
});

// =============================================================================
// 3. Refresh -- persistence, not navigation memory
// =============================================================================

describe('browser refresh', () => {
  it('13, 22, 36, M1/M2/M3: a fresh app restores all three results', async () => {
    let user = await launch();
    await open(user, 'Deal A');
    await doTheWork(user);
    await waitFor(() => expect(mockSaveTwoWay).toHaveBeenCalled());

    // The refresh. Every hook, every closure and every component is gone.
    cleanup();
    vi.clearAllMocks();
    mockListDeals.mockImplementation(async () => [...stored.values()].map(clone));
    mockGetDeal.mockImplementation(async (id: string) => clone(stored.get(id)!));

    user = await launch();
    await open(user, 'Deal A');

    await goTo(user, 'AI Analyst');
    expect(
      await within(workspacePanel('ai')).findByText(ANALYSIS.executive_summary),
    ).toBeTruthy();

    await goTo(user, 'Risk');
    expect(within(sensitivityPanel('one-way')).getByRole('table')).toBeTruthy();
    await user.click(screen.getByRole('tab', { name: 'Two-Way' }));
    expect(within(sensitivityPanel('two-way')).getByRole('table')).toBeTruthy();

    // And none of it was recomputed after the refresh.
    expect(mockAnalyze).not.toHaveBeenCalled();
    expect(mockAi).not.toHaveBeenCalled();
    expect(mockOneWay).not.toHaveBeenCalled();
    expect(mockTwoWay).not.toHaveBeenCalled();
  });

  it('24, 25: the baseline highlight and an undefined metric survive the restore', async () => {
    let user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await runOneWay(user);
    await waitFor(() => expect(mockSaveOneWay).toHaveBeenCalled());

    cleanup();
    mockGetDeal.mockImplementation(async (id: string) => clone(stored.get(id)!));
    user = await launch();
    await open(user, 'Deal A');
    await goTo(user, 'Risk');

    const scope = sensitivityPanel('one-way');
    const table = within(scope).getByRole('table');
    // 25 / M16: the undefined metric is still N/A, never a zero.
    expect(within(table).getByText('N/A')).toBeTruthy();
    expect(within(table).queryByText('0.00%')).toBeNull();
    // 24: the Base highlight is still on the candidate that equals the
    // response's own baseline, and the baseline line above the table still
    // states it. Both come from the stored response, not from a re-run.
    expect(table.querySelectorAll('.sensitivity-baseline').length).toBe(1);
    expect(within(table).getByText(/Base/)).toBeTruthy();
    expect(scope.querySelector('.sensitivity-baseline-line')?.textContent).toContain('6.25%');
  });

  it('37, 38: rows stay rows and columns stay columns after a restore', async () => {
    let user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await runTwoWay(user);
    await waitFor(() => expect(mockSaveTwoWay).toHaveBeenCalled());

    // What the analyst was looking at before the refresh. Captured rather than
    // hardcoded, so the assertion is "the editor came back as it was" and not
    // "the editor formats numbers this particular way".
    const rowValuesBefore = candidateValues(
      sensitivityPanel('two-way'),
      'Row Exit Cap Rate candidate value',
    );
    const columnValuesBefore = candidateValues(
      sensitivityPanel('two-way'),
      'Column Purchase Price candidate value',
    );
    expect(columnValuesBefore).toHaveLength(3);

    cleanup();
    mockGetDeal.mockImplementation(async (id: string) => clone(stored.get(id)!));
    user = await launch();
    await open(user, 'Deal A');
    await goTo(user, 'Risk');
    await user.click(screen.getByRole('tab', { name: 'Two-Way' }));

    // 2 rows of 3 columns, the shape that was run. A transposed restore would
    // be 3 rows of 2, which this cannot read as a pass.
    const rows = matrixRows(sensitivityPanel('two-way'));
    expect(rows.length).toBe(2);
    // Each row is a header cell plus three metric cells.
    expect(rows.every((row) => row.length === 3)).toBe(true);
    expect(
      candidateValues(sensitivityPanel('two-way'), 'Row Exit Cap Rate candidate value'),
    ).toEqual(rowValuesBefore);
    expect(
      candidateValues(sensitivityPanel('two-way'), 'Column Purchase Price candidate value'),
    ).toEqual(columnValuesBefore);
    // 32, 33: and the axes did not swap in storage either -- the stored
    // configuration still says which target is the rows and which the columns,
    // with two row values and three column values, in the analyst's order.
    const configuration = stored.get('deal-a')?.two_way_sensitivity_snapshot?.configuration;
    expect(configuration?.row_assumption).toBe('exit_cap_rate');
    expect(configuration?.column_assumption).toBe('purchase_price');
    expect(configuration?.row_values).toHaveLength(2);
    expect(configuration?.column_values).toHaveLength(3);
  });
});

// =============================================================================
// 4. Staleness -- an edit stops the result being presented as current
// =============================================================================

describe('an underwriting edit', () => {
  it('M20: an edit stops all three being presented as current', async () => {
    // **D5.8B changes what "stops presenting as current" looks like.**
    //
    // D5.8A withdrew the results. Human review asked for them back, marked
    // rather than removed, so all three now stay on screen carrying the
    // out-of-date notice. The mutant is unchanged and still killed: none of
    // them may read as describing the assumptions now on screen.
    const user = await launch();
    await open(user, 'Deal A');
    await doTheWork(user);
    await waitFor(() => expect(mockSaveTwoWay).toHaveBeenCalled());

    await editPurchasePrice(user, '31000000');

    await goTo(user, 'AI Analyst');
    const ai = workspacePanel('ai');
    expect(within(ai).getByText(ANALYSIS.executive_summary)).toBeTruthy();
    expect(within(ai).getByText('Out of date')).toBeTruthy();

    const one = await showSensitivity(user, 'One-Way');
    expect(within(one).getByRole('table')).toBeTruthy();
    expect(within(one).getByText('Out of date')).toBeTruthy();

    const two = await showSensitivity(user, 'Two-Way');
    expect(within(two).getByRole('table')).toBeTruthy();
    expect(within(two).getByText('Out of date')).toBeTruthy();
  });

  it('11: undoing the edit brings the saved analysis back, without re-running it', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await doTheWork(user);
    await waitFor(() => expect(mockSaveTwoWay).toHaveBeenCalled());

    const saved = await editPurchasePrice(user, '31000000');
    await goTo(user, 'Risk');
    expect(within(sensitivityPanel('one-way')).queryByRole('table')).toBeNull();

    // Back to exactly the saved value. Typed as the grouped string the field
    // was showing; `NumericInput` strips separators on the way in, so the form
    // state this restores is the same plain-digit string the deal was opened
    // with -- which is what the staleness comparison is made of.
    await goTo(user, 'Underwrite');
    await user.clear(purchasePriceField());
    await user.type(purchasePriceField(), saved);

    expect(
      within(await showSensitivity(user, 'One-Way')).getByRole('table'),
    ).toBeTruthy();
    await goTo(user, 'AI Analyst');
    expect(within(workspacePanel('ai')).getByText(ANALYSIS.executive_summary)).toBeTruthy();

    expect(mockAi).toHaveBeenCalledTimes(1);
    expect(mockOneWay).toHaveBeenCalledTimes(1);
    expect(mockTwoWay).toHaveBeenCalledTimes(1);
  });

  it('does not delete the saved snapshot merely because a field was edited', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await runOneWay(user);
    await waitFor(() => expect(mockSaveOneWay).toHaveBeenCalled());

    await editPurchasePrice(user, '31000000');

    // Nothing was written to clear it: the stored snapshot is exactly as it
    // was, and stops being *presented* rather than being destroyed.
    expect(stored.get('deal-a')?.one_way_sensitivity_snapshot).not.toBeNull();
    expect(mockSaveOneWay).toHaveBeenCalledTimes(1);
  });
});

// =============================================================================
// 5. Failures never destroy completed work
// =============================================================================

describe('a failed re-run', () => {
  it('13, M8: a failed AI regeneration leaves the previous report on screen', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await generateAi(user);
    await waitFor(() => expect(mockSaveAi).toHaveBeenCalled());

    mockAi.mockRejectedValueOnce(new ApiError('The AI provider is unavailable.'));
    await user.click(
      within(workspacePanel('ai')).getByRole('button', { name: 'Regenerate Analysis' }),
    );

    expect(
      await within(workspacePanel('ai')).findByText('The AI provider is unavailable.'),
    ).toBeTruthy();
    // The completed report is still there, and still saved. It is this
    // session's own report rather than a restored one, so it carries no
    // provenance note -- the error banner above it is what says the new run was
    // refused.
    expect(within(workspacePanel('ai')).getByText(ANALYSIS.executive_summary)).toBeTruthy();
    expect(stored.get('deal-a')?.ai_snapshot).not.toBeNull();
    expect(mockSaveAi).toHaveBeenCalledTimes(1);
  });

  it('26, 40, M9: a refused sensitivity leaves the last saved run available', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await runOneWay(user);
    await waitFor(() => expect(mockSaveOneWay).toHaveBeenCalled());

    mockOneWay.mockRejectedValueOnce(
      new ApiError('NON_POSITIVE_FORWARD_EXIT_NOI: the forward exit NOI is not positive.'),
    );
    const scope = sensitivityPanel('one-way');
    await user.click(within(scope).getByRole('button', { name: 'Run Sensitivity' }));

    // The refusal is surfaced as the backend worded it...
    expect(await within(scope).findByText(/NON_POSITIVE_FORWARD_EXIT_NOI/)).toBeTruthy();
    // ...beside the previous successful run, labelled as what it is. D5.8B
    // changed the wording from "the last saved run" to "your previous run":
    // the run is now kept whether it came from persistence or from this
    // session, so the line names its relation to the failed attempt rather
    // than its storage.
    expect(within(scope).getByText(/Showing your previous run/i)).toBeTruthy();
    expect(within(scope).getByRole('table')).toBeTruthy();
    // The inputs have not moved, so this is a current result beside a failed
    // attempt -- not a stale one. The two states stay distinct.
    expect(within(scope).queryByText('Out of date')).toBeNull();
    // And nothing was written: the failure did not replace the good snapshot.
    expect(mockSaveOneWay).toHaveBeenCalledTimes(1);
    expect(stored.get('deal-a')?.one_way_sensitivity_snapshot).not.toBeNull();
  });
});

// =============================================================================
// 6. The two sensitivities are independent
// =============================================================================

describe('one-way and two-way are independent', () => {
  it('42, 43, M10, M11: running one leaves the other exactly where it was', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await runOneWay(user);
    await runTwoWay(user);
    await waitFor(() => expect(mockSaveTwoWay).toHaveBeenCalled());

    // Both on screen at once.
    await user.click(screen.getByRole('tab', { name: 'One-Way' }));
    expect(within(sensitivityPanel('one-way')).getByRole('table')).toBeTruthy();
    await user.click(screen.getByRole('tab', { name: 'Two-Way' }));
    expect(within(sensitivityPanel('two-way')).getByRole('table')).toBeTruthy();

    // Re-running one-way writes only the one-way row.
    await user.click(screen.getByRole('tab', { name: 'One-Way' }));
    await user.click(
      within(sensitivityPanel('one-way')).getByRole('button', { name: 'Run Sensitivity' }),
    );
    await waitFor(() => expect(mockSaveOneWay).toHaveBeenCalledTimes(2));
    expect(mockSaveTwoWay).toHaveBeenCalledTimes(1);
    expect(stored.get('deal-a')?.two_way_sensitivity_snapshot).not.toBeNull();

    await user.click(screen.getByRole('tab', { name: 'Two-Way' }));
    expect(within(sensitivityPanel('two-way')).getByRole('table')).toBeTruthy();
  });

  it('44, 45: AI and sensitivity do not disturb each other', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await doTheWork(user);
    await waitFor(() => expect(mockSaveTwoWay).toHaveBeenCalled());

    await generateAi(user);
    await waitFor(() => expect(mockSaveAi).toHaveBeenCalledTimes(2));

    expect(stored.get('deal-a')?.one_way_sensitivity_snapshot).not.toBeNull();
    expect(stored.get('deal-a')?.two_way_sensitivity_snapshot).not.toBeNull();

    expect(
      within(await showSensitivity(user, 'One-Way')).getByRole('table'),
    ).toBeTruthy();
    expect(stored.get('deal-a')?.ai_snapshot).not.toBeNull();
  });
});

// =============================================================================
// 7. Product polish -- 49, 52-56, M18, M19
// =============================================================================

describe('AI Analyst product language', () => {
  it('56: the subtitle says the analysis is grounded in the underwriting results', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await goTo(user, 'AI Analyst');

    expect(
      within(workspacePanel('ai')).getByText('Analysis grounded in your underwriting results.'),
    ).toBeTruthy();
    expect(
      within(workspacePanel('ai')).queryByText(
        'Narrative built strictly from the deterministic analysis.',
      ),
    ).toBeNull();
  });

  it('52: with no report, the button reads Generate AI Analysis', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await goTo(user, 'AI Analyst');

    expect(aiButtonLabel()).toBe('Generate AI Analysis');
  });

  it('53, M19: with a current report, the button reads Regenerate Analysis', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await generateAi(user);

    expect(aiButtonLabel()).toBe('Regenerate Analysis');
    // A report just generated carries no provenance note: it came from the
    // button the analyst pressed, which needs no explaining.
    expect(
      within(workspacePanel('ai')).queryByText(/Showing the last saved report/i),
    ).toBeNull();
  });

  it('55: navigating away and back with unchanged inputs restores the report and Regenerate', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await generateAi(user);
    await waitFor(() => expect(mockSaveAi).toHaveBeenCalled());

    await open(user, 'Deal B');
    await open(user, 'Deal A');
    await goTo(user, 'AI Analyst');

    // The report is back, without an Analyze click and without a second AI
    // request, and the control says what pressing it would do.
    expect(
      await within(workspacePanel('ai')).findByText(ANALYSIS.executive_summary),
    ).toBeTruthy();
    expect(aiButtonLabel()).toBe('Regenerate Analysis');
    expect(
      within(workspacePanel('ai')).getByText(/Showing the last saved report/i),
    ).toBeTruthy();
    expect(mockAi).toHaveBeenCalledTimes(1);
  });

  it('54: an underwriting edit blocks regeneration until the deal is analyzed again', async () => {
    // **D5.8B replaces D5.8A's answer to the same requirement.**
    //
    // D5.8A dropped the report, so the panel fell back to "Analyze the deal
    // first" and the button honestly read Generate. D5.8B keeps the report, so
    // the button still reads Regenerate -- and the protection moves to where it
    // belongs: the control is disabled, with the reason in words, because the
    // deterministic analysis a new report would have to describe no longer
    // exists.
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await generateAi(user);

    await editPurchasePrice(user, '31000000');
    await goTo(user, 'AI Analyst');

    const ai = workspacePanel('ai');
    expect(within(ai).getByText('Out of date')).toBeTruthy();
    expect(
      within(ai).getByRole('button', { name: 'Regenerate Analysis' }),
    ).toHaveProperty('disabled', true);
    expect(within(ai).getByText(/Analyze the deal again/i)).toBeTruthy();
  });

  it('49, M18: Lease-Level offers no Break-Even Interpretation section', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await generateAi(user);

    const panel = workspacePanel('ai');
    const sections = within(panel)
      .getAllByRole('tab')
      .map((tab) => tab.textContent);

    expect(sections).toEqual([
      'Investment View',
      'Executive Summary',
      'Strengths',
      'Risks',
      'Return Drivers',
      'Downside Analysis',
      'Capital Structure',
      'Questions to Investigate',
      'Confidence / Data Gaps',
    ]);
    expect(within(panel).queryByText(ANALYSIS.break_even_analysis)).toBeNull();
  });
});

describe('Quick and Detailed keep their Break-Even Interpretation', () => {
  it('50, 51: the panel offers all ten sections when nothing says otherwise', () => {
    // Exactly the props Quick and Detailed pass -- neither supplies
    // `hasBreakEvenAnalysis`, so both get the default, which is the full report.
    render(
      <AiAnalystPanel
        analysis={ANALYSIS}
        isLoading={false}
        error={null}
        onGenerate={() => {}}
      />,
    );

    const sections = screen.getAllByRole('tab').map((tab) => tab.textContent);
    expect(sections).toContain('Break-Even Interpretation');
    expect(sections).toHaveLength(10);
  });

  it('50, 51: only the Lease-Level render site suppresses the section', () => {
    // Structural, and the reason the component takes a fact rather than a mode:
    // if a future edit passed the flag at Quick's or Detailed's call site, this
    // fails, and no amount of Lease-Level testing would have caught it.
    const renderSites = appSource.match(/<AiAnalystPanel/g) ?? [];
    expect(renderSites.length).toBe(3);

    const suppressions = appSource.match(/hasBreakEvenAnalysis=\{false\}/g) ?? [];
    expect(suppressions.length).toBe(1);

    const leaseLevelBlock = appSource.slice(appSource.indexOf('leaseLevel.aiAnalysis'));
    expect(leaseLevelBlock).toContain('hasBreakEvenAnalysis={false}');
  });
});
