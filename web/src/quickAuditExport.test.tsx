/**
 * Excel Export 1 -- the Quick Underwrite audit-workbook action.
 *
 * The workbook exports what is *stored*: the saved inputs and their saved
 * analysis. So the action is offered only for a saved Quick deal with no
 * unsaved change and a result for its current inputs, and says precisely what
 * to do otherwise. The server enforces eligibility again; its refusal is shown
 * verbatim. Nothing in `api.ts` is mocked in the App flows: `fetch` is replaced
 * by a small backend, so the real client builds the real request.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import App from './App';
import {
  ApiError,
  QUICK_AUDIT_FALLBACK_FILENAME,
  downloadQuickUnderwriteAuditWorkbook,
  filenameFromContentDisposition,
} from './api';
import { DealHeader } from './components/DealHeader';
import type { DealHeaderProps, WorkbookExportAction } from './components/DealHeader';
import capitalEconomicsFixture from './capitalEconomicsFixture.json';
import { DEFAULT_FORM_VALUES, buildAcquisitionRequest } from './convert';
import { clone } from './leaseLevelDealFixture';
import type { AcquisitionResults, Deal } from './types';

vi.setConfig({ testTimeout: 30_000, hookTimeout: 30_000 });

const EXPORT_ITEM = 'Export Excel audit (.xlsx)';
const QUICK_RESULTS = capitalEconomicsFixture.quick.v5_mixed.response as unknown as AcquisitionResults;
const FILENAME = 'Harbor Point - Quick Underwrite Audit.xlsx';
const DISPOSITION = `attachment; filename="${FILENAME}"; filename*=UTF-8''Harbor%20Point%20-%20Quick%20Underwrite%20Audit.xlsx`;

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// =============================================================================
// DealHeader
// =============================================================================

function renderHeader(workbookExport: WorkbookExportAction | null | undefined) {
  const props: DealHeaderProps = {
    dealName: 'Harbor Point',
    onDealNameChange: vi.fn(),
    operatingMode: 'quick',
    onOperatingModeChange: vi.fn(),
    isSavedDeal: true,
    isSaving: false,
    saveStatus: 'saved',
    lastSavedAt: null,
    error: null,
    onSaveDeal: vi.fn(),
    onAnalyze: vi.fn(),
    isAnalyzing: false,
    onDuplicateDeal: vi.fn(),
    onDeleteDeal: vi.fn(),
    workbookExport,
  };
  render(<DealHeader {...props} />);
}

function action(overrides: Partial<WorkbookExportAction> = {}): WorkbookExportAction {
  return { blockedReason: null, isExporting: false, onExport: vi.fn(), message: null, ...overrides };
}

async function openMenu(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'More deal actions' }));
  return screen.getByRole('menu');
}

describe('the header action', () => {
  it('is absent when the mode offers no workbook', async () => {
    const user = userEvent.setup();
    renderHeader(null);
    const menu = await openMenu(user);
    expect(within(menu).queryByRole('menuitem', { name: EXPORT_ITEM })).toBeNull();
  });

  it('runs the export and closes the menu when available', async () => {
    const user = userEvent.setup();
    const available = action();
    renderHeader(available);
    const menu = await openMenu(user);
    await user.click(within(menu).getByRole('menuitem', { name: EXPORT_ITEM }));
    expect(available.onExport).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('is disabled with the reason attached as its description when blocked', async () => {
    const user = userEvent.setup();
    const blocked = action({ blockedReason: 'Save the Deal first.' });
    renderHeader(blocked);
    const menu = await openMenu(user);
    const item = within(menu).getByRole('menuitem', { name: EXPORT_ITEM }) as HTMLButtonElement;
    expect(item.disabled).toBe(true);
    expect(item.getAttribute('aria-describedby')).toBe('workbook-export-note');
    expect(document.getElementById('workbook-export-note')?.textContent).toBe('Save the Deal first.');
    fireEvent.click(item);
    expect(blocked.onExport).not.toHaveBeenCalled();
  });

  it('announces a refusal as an alert and a success as a status', () => {
    renderHeader(action({ message: { tone: 'error', text: 'The saved analysis no longer matches.' } }));
    expect(screen.getByRole('alert').textContent).toBe('The saved analysis no longer matches.');
    cleanup();
    renderHeader(action({ message: { tone: 'status', text: `Exported ${FILENAME}` } }));
    expect(screen.getByRole('status').textContent).toBe(`Exported ${FILENAME}`);
  });

  it('shows progress while exporting', async () => {
    const user = userEvent.setup();
    renderHeader(action({ isExporting: true }));
    const menu = await openMenu(user);
    const item = within(menu).getByRole('menuitem', { name: 'Exporting Excel audit…' }) as HTMLButtonElement;
    expect(item.disabled).toBe(true);
  });
});

// =============================================================================
// The client
// =============================================================================

function binaryReply(status: number, headers: Record<string, string>, payload: unknown = null): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers(headers),
    blob: async () => new Blob(['PK-workbook']),
    json: async () => {
      if (payload === null) {
        throw new SyntaxError('not json');
      }
      return clone(payload);
    },
  } as unknown as Response;
}

describe('the client', () => {
  it('prefers the exact UTF-8 filename and falls back to the ASCII one', () => {
    expect(filenameFromContentDisposition(DISPOSITION)).toBe(FILENAME);
    expect(filenameFromContentDisposition(`attachment; filename="${FILENAME}"`)).toBe(FILENAME);
    expect(
      filenameFromContentDisposition("attachment; filename=\"Caf_ - Quick Underwrite Audit.xlsx\"; filename*=UTF-8''Caf%C3%A9%20-%20Quick%20Underwrite%20Audit.xlsx"),
    ).toBe('Café - Quick Underwrite Audit.xlsx');
    expect(filenameFromContentDisposition(null)).toBeNull();
    expect(filenameFromContentDisposition('inline')).toBeNull();
  });

  it('requests the one export route for the deal and returns bytes and filename', async () => {
    const fetchMock = vi.fn(async () => binaryReply(200, { 'Content-Disposition': DISPOSITION }));
    vi.stubGlobal('fetch', fetchMock);
    const download = await downloadQuickUnderwriteAuditWorkbook('deal/1');
    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/deals/deal%2F1/exports/quick-underwrite.xlsx',
    );
    expect(download.filename).toBe(FILENAME);
    expect(download.blob.size).toBeGreaterThan(0);
  });

  it('uses a fallback name when the header is unreadable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => binaryReply(200, {})));
    expect((await downloadQuickUnderwriteAuditWorkbook('d')).filename).toBe(QUICK_AUDIT_FALLBACK_FILENAME);
  });

  it('surfaces the server refusal message verbatim', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        binaryReply(409, {}, { detail: { code: 'analysis_stale', message: 'Analyze the current inputs and save.' } }),
      ),
    );
    await expect(downloadQuickUnderwriteAuditWorkbook('d')).rejects.toEqual(
      new ApiError('Analyze the current inputs and save.'),
    );
  });

  it('reports an unreachable backend and an unreadable refusal plainly', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('offline'); }));
    await expect(downloadQuickUnderwriteAuditWorkbook('d')).rejects.toThrow(/Could not reach the Anchor API/);
    vi.stubGlobal('fetch', vi.fn(async () => binaryReply(500, {})));
    await expect(downloadQuickUnderwriteAuditWorkbook('d')).rejects.toThrow('The audit workbook could not be exported.');
  });
});

// =============================================================================
// The application
// =============================================================================

interface Recorded {
  method: string;
  path: string;
}

let requests: Recorded[] = [];
let deals: Deal[] = [];
let exportReply: () => Response = () => binaryReply(200, { 'Content-Disposition': DISPOSITION });

function quickDeal(overrides: Partial<Deal> = {}): Deal {
  return {
    id: 'quick-1',
    name: 'Harbor Point',
    operating_mode: 'quick',
    inputs: buildAcquisitionRequest(DEFAULT_FORM_VALUES),
    terms: null,
    detailed_operating_inputs: null,
    property_inputs: null,
    operating_inputs: null,
    market_leasing: null,
    suites: null,
    leases: null,
    business_plan: { capital_items: [], owner_expense_items: [] },
    asset_type: 'multifamily',
    asset_subtype: 'Garden',
    deal_context: null,
    analysis_snapshot: clone(QUICK_RESULTS),
    ai_snapshot: null,
    one_way_sensitivity_snapshot: null,
    two_way_sensitivity_snapshot: null,
    created_at: '2026-09-12T09:00:00+00:00',
    updated_at: '2026-09-12T09:00:00+00:00',
    ...overrides,
  };
}

function reply(status: number, body: unknown): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => clone(body) } as Response;
}

async function backend(url: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const path = String(url).replace('http://127.0.0.1:8000', '');
  const method = init?.method ?? 'GET';
  requests.push({ method, path });
  if (method === 'GET' && path === '/deals') {
    return reply(200, deals);
  }
  if (path.endsWith('/exports/quick-underwrite.xlsx')) {
    return exportReply();
  }
  const single = /^\/deals\/([^/]+)$/.exec(path);
  if (method === 'GET' && single !== null) {
    const deal = deals.find((candidate) => candidate.id === decodeURIComponent(single[1]));
    return deal ? reply(200, deal) : reply(404, { detail: 'not found' });
  }
  return reply(500, {});
}

const exports = () => requests.filter((request) => request.path.endsWith('/exports/quick-underwrite.xlsx'));

let clicked: { href: string; download: string }[] = [];

beforeEach(() => {
  requests = [];
  clicked = [];
  deals = [quickDeal()];
  exportReply = () => binaryReply(200, { 'Content-Disposition': DISPOSITION });
  vi.stubGlobal('fetch', vi.fn(backend));
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:workbook') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    clicked.push({ href: this.href, download: this.download });
  });
});

type User = ReturnType<typeof userEvent.setup>;

async function launchAndOpen(name = 'Harbor Point'): Promise<User> {
  const user = userEvent.setup({ delay: null });
  render(<App />);
  const sidebar = await waitFor(() => {
    const list = document.querySelector('.sidebar-deal-list');
    expect(list).not.toBeNull();
    return list as HTMLElement;
  });
  await user.click(await within(sidebar).findByText(name));
  await waitFor(() => expect(screen.getByDisplayValue(name)).toBeTruthy());
  await waitFor(() =>
    expect(requests.some((request) => request.method === 'GET' && request.path.startsWith('/deals/'))).toBe(true),
  );
  return user;
}

async function exportItem(user: User): Promise<HTMLButtonElement> {
  await user.click(screen.getByRole('button', { name: 'More deal actions' }));
  return within(screen.getByRole('menu')).getByRole('menuitem', { name: EXPORT_ITEM }) as HTMLButtonElement;
}

describe('exporting from the Quick workspace', () => {
  it('downloads the saved, analysed deal under the server filename', async () => {
    const user = await launchAndOpen();
    const item = await exportItem(user);
    expect(item.disabled).toBe(false);
    await user.click(item);
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe(`Exported ${FILENAME}`));
    expect(exports()).toEqual([{ method: 'GET', path: '/deals/quick-1/exports/quick-underwrite.xlsx' }]);
    expect(clicked).toEqual([{ href: 'blob:workbook', download: FILENAME }]);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:workbook');
    // Exporting writes nothing.
    expect(requests.filter((request) => request.method !== 'GET')).toEqual([]);
  });

  it('drops the outcome line once the deal no longer matches what was exported', async () => {
    const user = await launchAndOpen();
    await user.click(await exportItem(user));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe(`Exported ${FILENAME}`));
    await user.type(screen.getByLabelText('Deal Name'), ' II');
    expect(screen.queryByText(`Exported ${FILENAME}`)).toBeNull();
  });

  it('is reachable and operable from the keyboard', async () => {
    const user = await launchAndOpen();
    const trigger = screen.getByRole('button', { name: 'More deal actions' });
    trigger.focus();
    await user.keyboard('{Enter}');
    const item = within(screen.getByRole('menu')).getByRole('menuitem', { name: EXPORT_ITEM });
    item.focus();
    await user.keyboard('{Enter}');
    await waitFor(() => expect(exports()).toHaveLength(1));
  });

  it('refuses unsaved changes and says what to do, sending nothing', async () => {
    const user = await launchAndOpen();
    // Any unsaved edit counts; the Deal Name is one the header always shows.
    await user.type(screen.getByLabelText('Deal Name'), ' II');
    expect(screen.getByText('Unsaved changes')).toBeTruthy();
    const item = await exportItem(user);
    expect(item.disabled).toBe(true);
    expect(document.getElementById('workbook-export-note')?.textContent).toBe(
      'Unsaved changes are not exported. Save the Deal and analyze the saved inputs first.',
    );
    fireEvent.click(item);
    expect(exports()).toEqual([]);
  });

  it('refuses a saved deal with no analysis', async () => {
    deals = [quickDeal({ analysis_snapshot: null })];
    const user = await launchAndOpen();
    const item = await exportItem(user);
    expect(item.disabled).toBe(true);
    expect(document.getElementById('workbook-export-note')?.textContent).toBe(
      'Analyze the saved inputs first. The workbook contains only a saved, current analysis.',
    );
  });

  it('refuses a deal that has never been saved', async () => {
    const user = userEvent.setup({ delay: null });
    render(<App />);
    await waitFor(() => expect(requests.some((request) => request.path === '/deals')).toBe(true));
    const item = await exportItem(user);
    expect(item.disabled).toBe(true);
    expect(document.getElementById('workbook-export-note')?.textContent).toBe(
      'Save this Deal, then analyze it, to export the Excel audit workbook.',
    );
  });

  it('shows the server refusal verbatim when the stored analysis is stale', async () => {
    exportReply = () =>
      binaryReply(409, {}, {
        detail: {
          code: 'analysis_stale',
          message: 'The saved analysis no longer matches the saved inputs. Analyze the current inputs and save the Deal, then export again.',
        },
      });
    const user = await launchAndOpen();
    await user.click(await exportItem(user));
    await waitFor(() =>
      expect(screen.getByRole('alert').textContent).toBe(
        'The saved analysis no longer matches the saved inputs. Analyze the current inputs and save the Deal, then export again.',
      ),
    );
    expect(clicked).toEqual([]);
  });

  it('never sends the Quick request from another workspace', async () => {
    // Excel Export 2 gave Detailed its own workbook, so the action is now
    // offered there too -- routed to the Detailed endpoint, which
    // `detailedAuditExport.test.tsx` pins. What stays true here is that
    // nothing but the Quick workspace can reach the Quick endpoint.
    const user = userEvent.setup({ delay: null });
    render(<App />);
    for (const mode of ['Detailed Underwrite', 'Lease-Level Underwrite']) {
      await user.click(screen.getByRole('tab', { name: mode }));
      await user.click(screen.getByRole('button', { name: 'More deal actions' }));
      const item = within(screen.getByRole('menu')).queryByRole('menuitem', { name: EXPORT_ITEM });
      if (item !== null) {
        // Unsaved workspace: the action is present but blocked, and clicking
        // it sends nothing.
        expect((item as HTMLButtonElement).disabled).toBe(true);
        fireEvent.click(item);
      }
      await user.keyboard('{Escape}');
    }
    expect(exports()).toEqual([]);
  });

  it('offers the Lease-Level workspace its own action, gated on saving first', async () => {
    const user = userEvent.setup({ delay: null });
    render(<App />);
    await user.click(screen.getByRole('tab', { name: 'Lease-Level Underwrite' }));
    await user.click(screen.getByRole('button', { name: 'More deal actions' }));
    const item = within(screen.getByRole('menu')).getByRole('menuitem', {
      name: EXPORT_ITEM,
    }) as HTMLButtonElement;
    expect(item.disabled).toBe(true);
    // Excel Export 3 gave Lease-Level a workbook of its own. An unsaved
    // Deal is still refused, and for its own reason: there is nothing saved to
    // audit yet.
    expect(document.getElementById('workbook-export-note')?.textContent).toContain(
      'Save this Deal to export the Excel audit workbook.',
    );
  });
});
