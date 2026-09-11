/**
 * D5.8B -- a persisted analytical result says whether it is still current.
 *
 * D5.8A made completed work survive navigation, a refresh and a restart. Human
 * review then found the state that created: a report or a matrix could be on
 * screen describing assumptions the analyst had since changed, with nothing
 * saying so. This file owns the answer.
 *
 * **Three states, never collapsed.** A result can be current, out of date, or
 * accompanied by a re-run that failed -- and the last two happen together
 * routinely. Every test below distinguishes them, because a single generic
 * "something is wrong" banner would lose the one distinction that matters: a
 * stale result is valid work about earlier inputs, and a failed run is no work
 * at all.
 *
 * **Staleness is derived, never stored.** It is the same comparison D5.8A used
 * to decide whether to restore a snapshot -- assumptions on screen against the
 * assumptions an artifact was produced from, with Deal Context counting for the
 * AI report and not for a sensitivity run, exactly as the two backend
 * fingerprints do. So putting an assumption back makes a result current again
 * with no re-run, and no test here has to arrange for a flag to be cleared.
 *
 * Driven through `App` against the same fake durable store D5.8A uses: the
 * artifacts these tests mark stale are ones the app genuinely saved.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
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
import fixture from './leaseLevelResultsFixture.json';
import {
  ANALYSIS,
  ONE_WAY_RESULT,
  TWO_WAY_RESULT,
  clone,
  makeDeal,
} from './leaseLevelDealFixture';
import { STALE_LABEL } from './components/StaleAnalysisNotice';
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

/** These tests drive whole analyst workflows through the real `App`; see the
 * same note in `leaseLevelAnalysisPersistence.test.tsx`. Time, never leniency:
 * nothing here waits on a timer. */
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

async function launch(): Promise<User> {
  const user = userEvent.setup({ delay: null });
  render(<App />);
  await screen.findByText('Deal A');
  return user;
}

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

function aiPanel(): HTMLElement {
  const element = document.getElementById('workspace-panel-ai');
  if (element === null) {
    throw new Error('No AI Analyst panel');
  }
  return element;
}

async function goTo(user: User, tab: string): Promise<void> {
  await user.click(screen.getByRole('tab', { name: tab }));
}

/** Both sensitivity panels stay mounted with the inactive one `hidden`, so a
 * role query must select the view before it can see the table. */
async function showSensitivity(user: User, view: 'One-Way' | 'Two-Way'): Promise<HTMLElement> {
  await goTo(user, 'Risk');
  await user.click(screen.getByRole('tab', { name: view }));
  const element = document.getElementById(
    `lease-level-sensitivity-panel-${view === 'One-Way' ? 'one-way' : 'two-way'}`,
  );
  if (element === null) {
    throw new Error(`No sensitivity panel for ${view}`);
  }
  return element;
}

async function analyze(user: User): Promise<void> {
  const before = mockAnalyze.mock.calls.length;
  await user.click(screen.getByRole('button', { name: /^Analyz/i }));
  await waitFor(() => expect(mockAnalyze.mock.calls.length).toBe(before + 1));
}

function aiButton(): HTMLButtonElement {
  return within(aiPanel()).getByRole('button', {
    name: /Generate AI Analysis|Regenerate Analysis/,
  }) as HTMLButtonElement;
}

async function generateAi(user: User): Promise<void> {
  await goTo(user, 'AI Analyst');
  await user.click(aiButton());
  await waitFor(() =>
    expect(within(aiPanel()).queryByText(ANALYSIS.executive_summary)).not.toBeNull(),
  );
}

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

async function runOneWay(user: User): Promise<HTMLElement> {
  const scope = await showSensitivity(user, 'One-Way');
  if (within(scope).queryAllByLabelText(/^Exit Cap Rate candidate value \d+$/).length === 0) {
    await enterCandidates(user, scope, 'Exit Cap Rate candidate value', ['6', '6.25']);
  }
  const before = mockOneWay.mock.calls.length;
  await user.click(within(scope).getByRole('button', { name: 'Run Sensitivity' }));
  await waitFor(() => expect(mockOneWay.mock.calls.length).toBe(before + 1));
  return scope;
}

async function runTwoWay(user: User): Promise<HTMLElement> {
  const scope = await showSensitivity(user, 'Two-Way');
  if (within(scope).queryAllByLabelText(/^Row Exit Cap Rate candidate value \d+$/).length === 0) {
    await enterCandidates(user, scope, 'Row Exit Cap Rate candidate value', ['6', '6.5']);
    await enterCandidates(user, scope, 'Column Purchase Price candidate value', [
      '29000000',
      '30000000',
    ]);
  }
  const before = mockTwoWay.mock.calls.length;
  await user.click(within(scope).getByRole('button', { name: 'Run Sensitivity' }));
  await waitFor(() => expect(mockTwoWay.mock.calls.length).toBe(before + 1));
  return scope;
}

function purchasePriceField(): HTMLInputElement {
  return document.getElementById('lease-level-terms-purchasePrice') as HTMLInputElement;
}

/** Edits Purchase Price and returns what the field held, so a test can put it
 * back to exactly that. */
async function editPurchasePrice(user: User, value: string): Promise<string> {
  await goTo(user, 'Underwrite');
  const field = purchasePriceField();
  const before = field.value;
  await user.clear(field);
  await user.type(field, value);
  return before;
}

async function editDealContext(user: User, value: string): Promise<void> {
  await goTo(user, 'Underwrite');
  const field = screen.getByLabelText(/Deal Context/i);
  await user.clear(field);
  await user.type(field, value);
}

/** The out-of-date notice inside one panel, or `null`. Found by its words --
 * the state must be readable, not inferred from a colour or a border. */
function staleNotice(scope: HTMLElement): HTMLElement | null {
  return within(scope).queryByText(STALE_LABEL);
}

function hasResultTable(scope: HTMLElement): boolean {
  return within(scope).queryByRole('table') !== null;
}

/** Analyze, generate, run both, and wait until all three are saved. */
async function doTheWork(user: User): Promise<void> {
  await analyze(user);
  await generateAi(user);
  await runOneWay(user);
  await runTwoWay(user);
  await waitFor(() => expect(mockSaveTwoWay).toHaveBeenCalled());
}

// =============================================================================
// 1-5. The AI report: current, then out of date
// =============================================================================

describe('the AI report', () => {
  it('1: says nothing at all while it matches the assumptions on screen', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await generateAi(user);

    expect(within(aiPanel()).getByText(ANALYSIS.executive_summary)).toBeTruthy();
    expect(staleNotice(aiPanel())).toBeNull();
    expect(aiButton()).toHaveProperty('disabled', false);
  });

  it('2, 3, 4, M1, M2: an edit keeps the report and marks it out of date', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await generateAi(user);

    await editPurchasePrice(user, '31000000');
    await goTo(user, 'AI Analyst');

    // 2 / M2: the report is still there, in full.
    expect(within(aiPanel()).getByText(ANALYSIS.executive_summary)).toBeTruthy();
    expect(within(aiPanel()).getByText(ANALYSIS.risks[0])).toBeTruthy();
    // 3 / M1: and unmistakably marked, in words.
    expect(staleNotice(aiPanel())).toBeTruthy();
    // 4: which say what changed and what to do about it.
    const message = within(aiPanel()).getByText(/assumptions have changed/i).textContent ?? '';
    expect(message).toMatch(/Re-analyze the deal/i);
    // Never dressed up as a failure -- nothing failed.
    expect(message).not.toMatch(/invalid|error|wrong|failed/i);
  });

  it('5: a stale report is announced as a status, not as an alert', async () => {
    // Accessibility: a standing condition of what is on screen, not an
    // interruption. It must reach a screen reader without seizing the moment,
    // and it must not be mistaken for the error region beside it.
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await generateAi(user);
    await editPurchasePrice(user, '31000000');
    await goTo(user, 'AI Analyst');

    const notice = within(aiPanel()).getByRole('status');
    expect(notice.textContent).toContain(STALE_LABEL);
    expect(within(aiPanel()).queryByRole('alert')).toBeNull();
  });
});

// =============================================================================
// 6-8. What the analyst can do about it
// =============================================================================

describe('regenerating a stale report', () => {
  it('6: is refused while no analysis of the current assumptions exists', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await generateAi(user);
    expect(mockAi).toHaveBeenCalledTimes(1);

    await editPurchasePrice(user, '31000000');
    await goTo(user, 'AI Analyst');

    // The control is disabled and says why, rather than leaving the analyst to
    // guess from a greyed-out button.
    expect(aiButton()).toHaveProperty('disabled', true);
    expect(within(aiPanel()).getByText(/Analyze the deal again/i)).toBeTruthy();

    // And the refusal is real, not decorative: clicking sends nothing.
    await user.click(aiButton());
    expect(mockAi).toHaveBeenCalledTimes(1);
  });

  it('7: stays out of date after the deal is re-analyzed, until it is regenerated', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await generateAi(user);

    await editPurchasePrice(user, '31000000');
    await analyze(user);
    await goTo(user, 'AI Analyst');

    // Fresh numbers exist, so regeneration is possible -- but the report on
    // screen was written about the numbers before the edit, and still says so.
    expect(staleNotice(aiPanel())).toBeTruthy();
    expect(within(aiPanel()).getByText(ANALYSIS.executive_summary)).toBeTruthy();
    expect(aiButton()).toHaveProperty('disabled', false);
    expect(within(aiPanel()).queryByText(/Analyze the deal again/i)).toBeNull();
    expect(mockAi).toHaveBeenCalledTimes(1);
  });

  it('8: a successful regeneration clears the notice', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await generateAi(user);

    await editPurchasePrice(user, '31000000');
    await analyze(user);

    const regenerated = { ...ANALYSIS, executive_summary: 'A revised reading of the deal.' };
    mockAi.mockResolvedValueOnce(regenerated);
    await goTo(user, 'AI Analyst');
    await user.click(aiButton());

    expect(await within(aiPanel()).findByText(regenerated.executive_summary)).toBeTruthy();
    expect(staleNotice(aiPanel())).toBeNull();
    expect(within(aiPanel()).queryByText(ANALYSIS.executive_summary)).toBeNull();
  });
});

// =============================================================================
// 9, 10, 26, 27, 28. A failed regeneration is a third state
// =============================================================================

describe('a failed regeneration', () => {
  it('9, M9: leaves the previous report exactly where it was', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await generateAi(user);

    mockAi.mockRejectedValueOnce(new ApiError('The AI provider is unavailable.'));
    await user.click(aiButton());

    expect(await within(aiPanel()).findByText('The AI provider is unavailable.')).toBeTruthy();
    expect(within(aiPanel()).getByText(ANALYSIS.executive_summary)).toBeTruthy();
    // Current inputs, so a failure is the only thing that happened.
    expect(staleNotice(aiPanel())).toBeNull();
    expect(within(aiPanel()).getByText(/Showing your previous report/i)).toBeTruthy();
  });

  it('10, 26, 27, M10: shows the failure AND the out-of-date notice together', async () => {
    // The state this gate exists to keep legible. The analyst edited an
    // assumption, re-analyzed, asked for a new report, and the provider failed.
    // Three facts are true at once and all three are on screen: the report is
    // old, the new attempt failed, and the old one is what they are looking at.
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await generateAi(user);

    await editPurchasePrice(user, '31000000');
    await analyze(user);
    await goTo(user, 'AI Analyst');

    mockAi.mockRejectedValueOnce(new ApiError('The AI provider is unavailable.'));
    await user.click(aiButton());

    await waitFor(() =>
      expect(within(aiPanel()).queryByText('The AI provider is unavailable.')).not.toBeNull(),
    );
    expect(staleNotice(aiPanel())).toBeTruthy();
    expect(within(aiPanel()).getByText(ANALYSIS.executive_summary)).toBeTruthy();
    // 27: the error did not replace the notice, and 28: the report is named as
    // the previous one rather than passed off as the answer to the failed call.
    expect(within(aiPanel()).getByText(/Showing your previous report/i)).toBeTruthy();
  });
});

// =============================================================================
// 11, 12, M5, M6. Deal Context counts for the report and not for a sensitivity
// =============================================================================

describe('a Deal Context edit', () => {
  it('11, 12, M5, M6: stales the AI report and leaves both sensitivities current', async () => {
    // The distinction the two backend fingerprints draw, visible in the
    // product. The AI Analyst reads the stated strategy and interprets it; a
    // sensitivity run re-underwrites the deal and never sees it. Collapsing the
    // two would either throw away valid matrices or leave a report interpreting
    // a strategy nobody holds any more.
    const user = await launch();
    await open(user, 'Deal A');
    await doTheWork(user);

    await editDealContext(user, 'Now a refinance-and-hold plan.');

    await goTo(user, 'AI Analyst');
    expect(staleNotice(aiPanel())).toBeTruthy();
    expect(within(aiPanel()).getByText(ANALYSIS.executive_summary)).toBeTruthy();

    const one = await showSensitivity(user, 'One-Way');
    expect(hasResultTable(one)).toBe(true);
    expect(staleNotice(one)).toBeNull();

    const two = await showSensitivity(user, 'Two-Way');
    expect(hasResultTable(two)).toBe(true);
    expect(staleNotice(two)).toBeNull();
  });

  it('leaves the AI report regenerable, because the numbers behind it never moved', async () => {
    // Deal Context is not an underwriting input, so it does not clear the
    // deterministic analysis -- and a new report can therefore be produced
    // immediately, without re-analyzing anything.
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await generateAi(user);

    await editDealContext(user, 'Now a refinance-and-hold plan.');
    await goTo(user, 'AI Analyst');

    expect(staleNotice(aiPanel())).toBeTruthy();
    expect(aiButton()).toHaveProperty('disabled', false);
    expect(within(aiPanel()).queryByText(/Analyze the deal again/i)).toBeNull();
  });
});

// =============================================================================
// 13-23. The two sensitivities
// =============================================================================

describe('one-way sensitivity', () => {
  it('13: says nothing while it matches the assumptions on screen', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    const scope = await runOneWay(user);

    expect(hasResultTable(scope)).toBe(true);
    expect(staleNotice(scope)).toBeNull();
  });

  it('14, 15, M3: an edit keeps the whole table and marks it out of date', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await runOneWay(user);

    await editPurchasePrice(user, '31000000');
    const scope = await showSensitivity(user, 'One-Way');

    // Everything the run produced is still readable: candidates, rows, the
    // baseline line and the Base highlight.
    expect(hasResultTable(scope)).toBe(true);
    expect(
      within(scope)
        .getAllByLabelText(/^Exit Cap Rate candidate value \d+$/)
        .map((field) => (field as HTMLInputElement).value),
    ).toEqual(['6', '6.25']);
    // The Base highlight and the baseline line both survive -- queried by the
    // classes that carry them, because "Base" also appears inside the baseline
    // sentence above the table.
    expect(scope.querySelectorAll('.sensitivity-baseline-tag').length).toBe(1);
    expect(scope.querySelector('.sensitivity-baseline-line')).not.toBeNull();
    // And the whole thing is marked.
    expect(staleNotice(scope)).toBeTruthy();
    expect(within(scope).getByText(/sensitivity again/i)).toBeTruthy();
  });

  it('16: a successful re-run clears the notice and replaces the snapshot', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await runOneWay(user);
    await waitFor(() => expect(mockSaveOneWay).toHaveBeenCalledTimes(1));

    await editPurchasePrice(user, '31000000');
    await analyze(user);
    const scope = await runOneWay(user);

    expect(staleNotice(scope)).toBeNull();
    expect(hasResultTable(scope)).toBe(true);
  });

  it('17, 22, M8, M10: a refused re-run keeps both the table and the notice', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await runOneWay(user);

    await editPurchasePrice(user, '31000000');
    const scope = await showSensitivity(user, 'One-Way');

    mockOneWay.mockRejectedValueOnce(
      new ApiError('NON_POSITIVE_FORWARD_EXIT_NOI: the forward exit NOI is not positive.'),
    );
    await user.click(within(scope).getByRole('button', { name: 'Run Sensitivity' }));

    await waitFor(() =>
      expect(within(scope).queryByText(/NON_POSITIVE_FORWARD_EXIT_NOI/)).not.toBeNull(),
    );
    // All three facts, all three visible.
    expect(hasResultTable(scope)).toBe(true);
    expect(staleNotice(scope)).toBeTruthy();
    expect(within(scope).getByText(/Showing your previous run/i)).toBeTruthy();
  });
});

describe('two-way sensitivity', () => {
  it('18: says nothing while it matches the assumptions on screen', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    const scope = await runTwoWay(user);

    expect(hasResultTable(scope)).toBe(true);
    expect(staleNotice(scope)).toBeNull();
  });

  it('19, 20, M3: an edit keeps the matrix and marks it out of date', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await runTwoWay(user);

    await editPurchasePrice(user, '31000000');
    const scope = await showSensitivity(user, 'Two-Way');

    const rows = within(scope).getByRole('table').querySelectorAll('tbody tr');
    expect(rows.length).toBe(TWO_WAY_RESULT.row_values.length);
    expect(staleNotice(scope)).toBeTruthy();
  });

  it('21: a successful re-run clears the notice', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await runTwoWay(user);

    await editPurchasePrice(user, '31000000');
    await analyze(user);
    const scope = await runTwoWay(user);

    expect(staleNotice(scope)).toBeNull();
    expect(hasResultTable(scope)).toBe(true);
  });

  it('22: a refused re-run keeps both the matrix and the notice', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await runTwoWay(user);

    await editPurchasePrice(user, '31000000');
    const scope = await showSensitivity(user, 'Two-Way');

    mockTwoWay.mockRejectedValueOnce(new ApiError('The sensitivity run was refused.'));
    await user.click(within(scope).getByRole('button', { name: 'Run Sensitivity' }));

    await waitFor(() =>
      expect(within(scope).queryByText('The sensitivity run was refused.')).not.toBeNull(),
    );
    expect(hasResultTable(scope)).toBe(true);
    expect(staleNotice(scope)).toBeTruthy();
    expect(within(scope).getByText(/Showing your previous run/i)).toBeTruthy();
  });
});

describe('the two sensitivities go stale independently of each other', () => {
  it('23: re-running one leaves the other out of date, and does not disturb it', async () => {
    const user = await launch();
    await open(user, 'Deal A');
    await analyze(user);
    await runOneWay(user);
    await runTwoWay(user);

    await editPurchasePrice(user, '31000000');
    await analyze(user);
    // Only the one-way run is repeated against the new assumptions.
    await runOneWay(user);

    const one = await showSensitivity(user, 'One-Way');
    expect(staleNotice(one)).toBeNull();

    const two = await showSensitivity(user, 'Two-Way');
    expect(hasResultTable(two)).toBe(true);
    expect(staleNotice(two)).toBeTruthy();
  });
});

// =============================================================================
// 24, 25. Staleness follows the deal, not the session
// =============================================================================

describe('staleness is derived, not remembered', () => {
  it('24: a Deal switch and a refresh both show a restored result as current', async () => {
    let user = await launch();
    await open(user, 'Deal A');
    await doTheWork(user);

    // Away and back.
    await open(user, 'Deal B');
    await open(user, 'Deal A');
    await goTo(user, 'AI Analyst');
    expect(within(aiPanel()).getByText(ANALYSIS.executive_summary)).toBeTruthy();
    expect(staleNotice(aiPanel())).toBeNull();
    expect(staleNotice(await showSensitivity(user, 'One-Way'))).toBeNull();

    // And a refresh: every hook and closure destroyed, only the store left.
    cleanup();
    mockGetDeal.mockImplementation(async (id: string) => clone(stored.get(id)!));
    user = await launch();
    await open(user, 'Deal A');
    await goTo(user, 'AI Analyst');
    expect(within(aiPanel()).getByText(ANALYSIS.executive_summary)).toBeTruthy();
    expect(staleNotice(aiPanel())).toBeNull();
    expect(staleNotice(await showSensitivity(user, 'Two-Way'))).toBeNull();
  });

  it('25, M4, M7: putting the assumption back makes all three current again', async () => {
    // The rule that makes staleness safe to derive rather than store: it is a
    // statement about what is on screen right now, so undoing an edit undoes it,
    // with no re-run, no extra click and no flag to clear. A stored boolean
    // would have stayed true here.
    const user = await launch();
    await open(user, 'Deal A');
    await doTheWork(user);

    const saved = await editPurchasePrice(user, '31000000');
    await goTo(user, 'AI Analyst');
    expect(staleNotice(aiPanel())).toBeTruthy();
    expect(staleNotice(await showSensitivity(user, 'One-Way'))).toBeTruthy();

    await goTo(user, 'Underwrite');
    await user.clear(purchasePriceField());
    await user.type(purchasePriceField(), saved);

    await goTo(user, 'AI Analyst');
    expect(staleNotice(aiPanel())).toBeNull();
    expect(within(aiPanel()).getByText(ANALYSIS.executive_summary)).toBeTruthy();
    expect(staleNotice(await showSensitivity(user, 'One-Way'))).toBeNull();
    expect(staleNotice(await showSensitivity(user, 'Two-Way'))).toBeNull();

    // Nothing was recomputed to get back here.
    expect(mockAi).toHaveBeenCalledTimes(1);
    expect(mockOneWay).toHaveBeenCalledTimes(1);
    expect(mockTwoWay).toHaveBeenCalledTimes(1);
  });

  it('saving edited assumptions never promotes a stale result to current', async () => {
    // The one moment a stale artifact could be certified against inputs it was
    // never produced from: Save is what makes the edited assumptions the deal's
    // own. The result stays on screen, stays marked, and is not written.
    const user = await launch();
    await open(user, 'Deal A');
    await doTheWork(user);
    const savedAiWrites = mockSaveAi.mock.calls.length;

    await editPurchasePrice(user, '31000000');
    await user.click(screen.getByRole('button', { name: /Update Deal|Save Deal/i }));
    await waitFor(() => expect(mockUpdateDeal).toHaveBeenCalled());

    await goTo(user, 'AI Analyst');
    expect(within(aiPanel()).getByText(ANALYSIS.executive_summary)).toBeTruthy();
    expect(staleNotice(aiPanel())).toBeTruthy();
    expect(staleNotice(await showSensitivity(user, 'One-Way'))).toBeTruthy();
    // Nothing stale was attached to the freshly-saved assumptions.
    expect(mockSaveAi.mock.calls.length).toBe(savedAiWrites);
  });
});

// =============================================================================
// Quick and Detailed are untouched
// =============================================================================

describe('the shared AI panel is unchanged for the other two modes', () => {
  it('renders no out-of-date notice when no caller supplies one', async () => {
    // Quick and Detailed pass neither `isStale` nor `generateBlockedReason`, so
    // both default off and their panel is exactly what it was.
    const { AiAnalystPanel } = await import('./components/AiAnalystPanel');
    render(
      <AiAnalystPanel
        analysis={ANALYSIS}
        isLoading={false}
        error={null}
        onGenerate={() => {}}
      />,
    );

    expect(screen.queryByText(STALE_LABEL)).toBeNull();
    expect(screen.queryByRole('status')).toBeNull();
    expect(
      screen.getByRole('button', { name: 'Regenerate Analysis' }),
    ).toHaveProperty('disabled', false);
  });
});
