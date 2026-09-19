/** Second P7.9 / AM1 QA pass -- the monthly workflow's three interaction fixes.
 *
 * Each test drives the real `useAssetPerformance` hook under the real
 * `ManagedAssetWorkspace`, with the API client mocked and resolved by hand, so
 * the window between "the analyst acted" and "the server answered" is a state
 * the test inspects rather than a race it hopes to win.
 *
 * 1. **Stale duplicate-month error.** "A report for 2027-03-01 already exists"
 *    stayed on screen after the analyst picked another month. It now clears the
 *    moment the month changes -- and only that refusal does.
 * 2. **Update Commentary opened the whole actuals form.** It now opens a focused
 *    commentary editor with sensible focus on open, cancel and save, and saves
 *    through the commentary-only route: the request carries the note and
 *    nothing else, so it can never write back stale actual figures.
 * 3. **The dashboard collapsed while a save was re-read.** The last confirmed
 *    dashboard now stays, marked busy, until the re-read settles; a failed
 *    re-read shows its error instead of leaving old figures looking current.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ManagedAssetWorkspace } from './components/ManagedAssetWorkspace';
import { DEMO_ASSET, DEMO_PERFORMANCE, DEMO_REPORT } from './assetManagementFixture';
import type {
  AssetPerformanceResponse,
  ManagedAsset,
  MonthlyAssetReport,
} from './assetManagementTypes';
import { useAssetPerformance } from './useManagedAssets';
import { withLfLineEndings } from './testSourceText';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    listMonthlyReports: vi.fn(),
    readAssetPerformance: vi.fn(),
    createMonthlyReport: vi.fn(),
    updateMonthlyReportActuals: vi.fn(),
    updateMonthlyReportCommentary: vi.fn(),
  };
});

const api = await import('./api');
const listMonthlyReports = vi.mocked(api.listMonthlyReports);
const readAssetPerformance = vi.mocked(api.readAssetPerformance);
const createMonthlyReport = vi.mocked(api.createMonthlyReport);
const updateMonthlyReportActuals = vi.mocked(api.updateMonthlyReportActuals);
const updateMonthlyReportCommentary = vi.mocked(api.updateMonthlyReportCommentary);

afterEach(cleanup);

beforeEach(() => {
  vi.clearAllMocks();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const ASSET: ManagedAsset = { ...DEMO_ASSET, id: 'asset-a' };
const MARCH = '2027-03-01';
const REPORT: MonthlyAssetReport = { ...DEMO_REPORT, managed_asset_id: 'asset-a' };
const PERFORMANCE: AssetPerformanceResponse = { ...DEMO_PERFORMANCE, managed_asset: ASSET };

/** March's result with a different actual NOI on the summary card, and a
 * different commentary, so "the re-read landed" is visible. */
function afterSave(actualNoi: number, commentary: string): AssetPerformanceResponse {
  const monthly = PERFORMANCE.result.monthly;
  return {
    ...PERFORMANCE,
    result: {
      ...PERFORMANCE.result,
      commentary,
      monthly: { ...monthly, actual: { ...monthly.actual, net_operating_income: actualNoi } },
    },
  };
}

function Harness() {
  const state = useAssetPerformance(ASSET.id);
  return (
    <ManagedAssetWorkspace
      asset={ASSET}
      state={state}
      onViewAcquisitionBasis={vi.fn()}
      onDelete={vi.fn().mockResolvedValue(undefined)}
    />
  );
}

function noiOnScreen(): string | null {
  const card = screen.queryByRole('region', { name: 'Net Operating Income' });
  return card?.querySelector('.am-card-value')?.textContent ?? null;
}

/** Renders the workspace with March loaded and settled. */
async function renderLoaded() {
  listMonthlyReports.mockResolvedValue([REPORT]);
  readAssetPerformance.mockResolvedValue(PERFORMANCE);
  const view = render(<Harness />);
  await act(async () => {});
  expect(noiOnScreen()).toBe('$61,500');
  return view;
}

function monthInput(): HTMLInputElement {
  return screen.getByLabelText('Reporting Month', { selector: 'input' }) as HTMLInputElement;
}

// =============================================================================
// 1. The duplicate-month error clears when the month changes
// =============================================================================

describe('a duplicate-month refusal clears as soon as the month changes', () => {
  const DUPLICATE = 'A report for 2027-03-01 already exists for this asset.';

  it('shows the refusal, then removes it on a month change without resubmitting', async () => {
    await renderLoaded();
    createMonthlyReport.mockRejectedValue(new api.MonthlyReportExistsError(DUPLICATE));

    await userEvent.click(screen.getByRole('button', { name: 'Add Month' }));
    fireEvent.change(monthInput(), { target: { value: '2027-03' } });
    await userEvent.click(screen.getByRole('button', { name: 'Save Monthly Report' }));

    // 1-2: submitted once, refused, and the refusal is on screen.
    expect(createMonthlyReport).toHaveBeenCalledTimes(1);
    expect((await screen.findByRole('alert')).textContent).toBe(DUPLICATE);

    // 3-4: a different month clears it -- no second submission.
    fireEvent.change(monthInput(), { target: { value: '2027-04' } });
    expect(screen.queryByText(DUPLICATE)).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(createMonthlyReport).toHaveBeenCalledTimes(1);
  });

  it('keeps any other refusal, because a month change does not answer it', async () => {
    await renderLoaded();
    const invalid = 'budget.rental_revenue: must be a finite, non-negative number';
    createMonthlyReport.mockRejectedValue(
      new api.AssetManagementError(invalid, [
        { code: 'invalid_value', scope: 'budget', field: 'rental_revenue', message: invalid },
      ]),
    );

    await userEvent.click(screen.getByRole('button', { name: 'Add Month' }));
    fireEvent.change(monthInput(), { target: { value: '2027-04' } });
    await userEvent.click(screen.getByRole('button', { name: 'Save Monthly Report' }));
    expect((await screen.findByRole('alert')).textContent).toBe(invalid);

    fireEvent.change(monthInput(), { target: { value: '2027-05' } });
    expect(screen.getByRole('alert').textContent).toBe(invalid);
  });

  it('keeps the typed duplicate refusal on the wire as the client’s own error class', () => {
    const error = new api.MonthlyReportExistsError(DUPLICATE);
    // Every existing caller that handles the base class still does.
    expect(error).toBeInstanceOf(api.AssetManagementError);
    expect(error.message).toBe(DUPLICATE);
  });
});

// =============================================================================
// 2. Update Commentary is a focused interaction
// =============================================================================

describe('Update Commentary edits the commentary and nothing else', () => {
  function commentarySection(): HTMLElement {
    return screen
      .getByRole('heading', { name: 'Management Commentary', level: 3 })
      .closest('section') as HTMLElement;
  }

  it('opens a focused editor: the month, the field, Cancel and Save -- no figures', async () => {
    await renderLoaded();
    await userEvent.click(screen.getByRole('button', { name: 'Update Commentary' }));

    const form = screen.getByRole('form', { name: 'Commentary for March 2027' });
    const field = within(form).getByRole('textbox', { name: 'Management Commentary' });
    expect(document.activeElement).toBe(field);
    expect((field as HTMLTextAreaElement).value).toBe(REPORT.commentary);
    expect(within(form).getAllByRole('button').map((button) => button.textContent)).toEqual([
      'Cancel',
      'Save Commentary',
    ]);
    // Not the actuals form: no figure can be changed from here.
    expect(screen.queryByRole('heading', { name: 'Edit Actual Results' })).toBeNull();
    expect(within(form).getAllByRole('textbox')).toHaveLength(1);
    expect(form.querySelectorAll('input')).toHaveLength(0);
    expect(document.querySelectorAll('input.am-input')).toHaveLength(0);
    // It opens inside the commentary panel, with the dashboard still in place.
    expect(commentarySection().contains(form)).toBe(true);
    expect(noiOnScreen()).toBe('$61,500');
  });

  it('cancels without writing and returns focus to Update Commentary', async () => {
    await renderLoaded();
    await userEvent.click(screen.getByRole('button', { name: 'Update Commentary' }));
    await userEvent.type(screen.getByRole('textbox', { name: 'Management Commentary' }), ' Draft.');
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(updateMonthlyReportCommentary).not.toHaveBeenCalled();
    expect(updateMonthlyReportActuals).not.toHaveBeenCalled();
    expect(screen.queryByRole('form', { name: 'Commentary for March 2027' })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Update Commentary' }));
  });

  it('cancels on Escape too, without writing', async () => {
    await renderLoaded();
    await userEvent.click(screen.getByRole('button', { name: 'Update Commentary' }));
    await userEvent.keyboard('{Escape}');
    expect(updateMonthlyReportCommentary).not.toHaveBeenCalled();
    expect(updateMonthlyReportActuals).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Update Commentary' }));
  });

  it('saves the commentary alone, through the commentary-only route', async () => {
    await renderLoaded();
    updateMonthlyReportCommentary.mockResolvedValue({ ...REPORT, commentary: 'Leasing recovered.' });
    await userEvent.click(screen.getByRole('button', { name: 'Update Commentary' }));
    const field = screen.getByRole('textbox', { name: 'Management Commentary' });
    await userEvent.clear(field);
    await userEvent.type(field, '  Leasing recovered.  ');
    await userEvent.click(screen.getByRole('button', { name: 'Save Commentary' }));

    // The request is the asset, the month and the note -- no actual or budget
    // object travels, and the actual-results route is never called.
    expect(updateMonthlyReportCommentary).toHaveBeenCalledTimes(1);
    expect(updateMonthlyReportCommentary.mock.calls[0]).toEqual([
      'asset-a',
      MARCH,
      'Leasing recovered.',
    ]);
    expect(updateMonthlyReportActuals).not.toHaveBeenCalled();
    expect(createMonthlyReport).not.toHaveBeenCalled();
    // Closed, with focus on a stable target: the section heading.
    expect(screen.queryByRole('form', { name: 'Commentary for March 2027' })).toBeNull();
    expect(document.activeElement).toBe(
      screen.getByRole('heading', { name: 'Management Commentary', level: 3 }),
    );
  });

  it('sends an emptied commentary as none written, never as whitespace', async () => {
    await renderLoaded();
    updateMonthlyReportCommentary.mockResolvedValue({ ...REPORT, commentary: null });
    await userEvent.click(screen.getByRole('button', { name: 'Update Commentary' }));
    const field = screen.getByRole('textbox', { name: 'Management Commentary' });
    await userEvent.clear(field);
    await userEvent.type(field, '   ');
    await userEvent.click(screen.getByRole('button', { name: 'Save Commentary' }));
    expect(updateMonthlyReportCommentary.mock.calls[0][2]).toBeNull();
  });

  it('keeps the editor and the draft open, with the reason, when the save fails', async () => {
    await renderLoaded();
    updateMonthlyReportCommentary.mockRejectedValue(
      new api.AssetManagementError('The monthly report could not be saved.'),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Update Commentary' }));
    const field = screen.getByRole('textbox', { name: 'Management Commentary' });
    await userEvent.type(field, ' Added.');
    await userEvent.click(screen.getByRole('button', { name: 'Save Commentary' }));

    expect((await screen.findByRole('alert')).textContent).toBe(
      'The monthly report could not be saved.',
    );
    expect(screen.getByRole('form', { name: 'Commentary for March 2027' })).toBeTruthy();
    expect((field as HTMLTextAreaElement).value).toBe(`${REPORT.commentary} Added.`);
  });

  it('cannot be submitted twice while its save is pending', async () => {
    await renderLoaded();
    const pending = deferred<MonthlyAssetReport>();
    updateMonthlyReportCommentary.mockReturnValue(pending.promise);
    await userEvent.click(screen.getByRole('button', { name: 'Update Commentary' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save Commentary' }));

    const saving = screen.getByRole('button', { name: 'Saving…' }) as HTMLButtonElement;
    expect(saving.disabled).toBe(true);
    await userEvent.click(saving);
    expect(updateMonthlyReportCommentary).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('form', { name: 'Commentary for March 2027' }).getAttribute('aria-busy')).toBe(
      'true',
    );
    await act(async () => pending.resolve(REPORT));
  });

  it('leaves the full actuals editor behind Edit Actuals', async () => {
    await renderLoaded();
    await userEvent.click(screen.getAllByRole('button', { name: 'Edit Actuals' })[0]);
    expect(screen.getByRole('heading', { name: 'Edit Actual Results' })).toBeTruthy();
    expect(screen.getByLabelText('Actual Rental Revenue')).toBeTruthy();
  });
});

// =============================================================================
// 3. A save's re-read keeps the confirmed dashboard in place
// =============================================================================

describe('a save keeps the confirmed dashboard while the month is re-read', () => {
  /** Holds the next reports and performance reads open until the test says. */
  function holdTheReRead() {
    const reports = deferred<MonthlyAssetReport[]>();
    const performance = deferred<AssetPerformanceResponse>();
    listMonthlyReports.mockReturnValue(reports.promise);
    readAssetPerformance.mockReturnValue(performance.promise);
    return { reports, performance };
  }

  async function saveCommentary(text: string) {
    await userEvent.click(screen.getByRole('button', { name: 'Update Commentary' }));
    const field = screen.getByRole('textbox', { name: 'Management Commentary' });
    await userEvent.clear(field);
    await userEvent.type(field, text);
    await userEvent.click(screen.getByRole('button', { name: 'Save Commentary' }));
  }

  it('never drops to an empty or "no report" state between the save and the re-read', async () => {
    const { container } = await renderLoaded();
    updateMonthlyReportCommentary.mockResolvedValue({ ...REPORT, commentary: 'Recovered.' });
    const reRead = holdTheReRead();

    await saveCommentary('Recovered.');

    // The save is confirmed; its re-read is still in flight.
    expect(updateMonthlyReportCommentary).toHaveBeenCalledTimes(1);
    expect(noiOnScreen()).toBe('$61,500');
    expect(screen.getByRole('heading', { name: 'March 2027 Operating Statement' })).toBeTruthy();
    expect(screen.queryByText('Loading monthly reports')).toBeNull();
    expect(screen.queryByText('No reporting yet')).toBeNull();
    expect(screen.queryByText(/performance…/)).toBeNull();

    // Busy, said in words, and nothing can be submitted on top of it.
    const dashboard = container.querySelector('.am-dashboard') as HTMLElement;
    expect(dashboard.getAttribute('aria-busy')).toBe('true');
    expect(container.querySelector('.am-refresh-status')?.textContent).toBe(
      'Updating March 2027 with the saved report…',
    );
    for (const name of ['Edit Actuals', 'Update Commentary', 'Add Month']) {
      for (const button of screen.getAllByRole('button', { name })) {
        expect((button as HTMLButtonElement).disabled, name).toBe(true);
      }
    }

    // The re-read lands: the saved result replaces the old one, and the busy
    // state ends.
    await act(async () => {
      reRead.reports.resolve([{ ...REPORT, commentary: 'Recovered.' }]);
      reRead.performance.resolve(afterSave(70000, 'Recovered.'));
    });
    expect(noiOnScreen()).toBe('$70,000');
    expect(screen.getByText('Recovered.')).toBeTruthy();
    expect(dashboard.getAttribute('aria-busy')).toBe('false');
    expect(container.querySelector('.am-refresh-status')?.textContent).toBe('');
    expect(
      (screen.getByRole('button', { name: 'Update Commentary' }) as HTMLButtonElement).disabled,
    ).toBe(false);
  });

  it('keeps the dashboard in place after a full actuals save, too', async () => {
    await renderLoaded();
    updateMonthlyReportActuals.mockResolvedValue(REPORT);
    holdTheReRead();

    await userEvent.click(screen.getAllByRole('button', { name: 'Edit Actuals' })[0]);
    await userEvent.click(screen.getByRole('button', { name: 'Save Actual Results' }));

    expect(updateMonthlyReportActuals).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('heading', { name: 'Edit Actual Results' })).toBeNull();
    expect(noiOnScreen()).toBe('$61,500');
    expect(screen.queryByText('Loading monthly reports')).toBeNull();
  });

  it('shows a failed re-read as an error and drops the old figures', async () => {
    await renderLoaded();
    updateMonthlyReportCommentary.mockResolvedValue(REPORT);
    const reRead = holdTheReRead();

    await saveCommentary('Recovered.');
    expect(noiOnScreen()).toBe('$61,500');

    await act(async () => {
      reRead.reports.resolve([REPORT]);
      reRead.performance.reject(new api.AssetManagementError('The server is unavailable.'));
    });
    expect(screen.getByRole('alert').textContent).toContain('The server is unavailable.');
    // Not left on screen looking current.
    expect(noiOnScreen()).toBeNull();
  });
});

// =============================================================================
// 4. The focused commentary path never reads or sends a figure
// =============================================================================

describe('the commentary path is distinct from the actual-results path', () => {
  const SOURCES = Object.fromEntries(
    Object.entries(
      import.meta.glob(['./useManagedAssets.ts', './components/ManagedAssetWorkspace.tsx'], {
        query: '?raw',
        eager: true,
        import: 'default',
      }) as Record<string, string>,
    ).map(([path, text]) => [path, withLfLineEndings(text)]),
  );

  /** The body of `const name = ...` up to the first line closing it. */
  function constBody(source: string, name: string): string {
    const start = source.indexOf(`const ${name} =`);
    expect(start, name).toBeGreaterThan(-1);
    const end = source.indexOf('\n  };', start);
    return source.slice(start, end);
  }

  it('the workspace saves commentary without reading any report figure', () => {
    const body = constBody(SOURCES['./components/ManagedAssetWorkspace.tsx'], 'saveCommentary');
    expect(body).toContain('state.saveCommentary(');
    expect(body).not.toMatch(/\.actual\b|\.budget\b|saveActuals|selectedReport/);
  });

  it('the hook sends it through the commentary-only client, not the actuals one', () => {
    const hook = SOURCES['./useManagedAssets.ts'];
    const start = hook.indexOf('const saveCommentary = useCallback(');
    const body = hook.slice(start, hook.indexOf('[managedAssetId],', start));
    expect(body).toContain('updateMonthlyReportCommentary(managedAssetId, month, commentary)');
    expect(body).not.toMatch(/updateMonthlyReportActuals|actual|budget/);
  });
});
