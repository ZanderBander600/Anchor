/**
 * Excel Export 2 -- the Detailed Underwrite audit-workbook action.
 *
 * The action is the one Excel Export 1 introduced; what this gate adds is a
 * second mode behind it. So what is tested here is mode routing and the
 * Detailed workspace's own eligibility: a Detailed deal exports through the
 * Detailed endpoint, a Quick deal still exports through the Quick one, and
 * Lease-Level says honestly that it has no workbook. The Detailed workspace
 * keeps its own saved id, dirty flag and result, so its blocked reasons are
 * driven by those and not by whatever the Quick workspace happens to hold.
 *
 * Nothing in `api.ts` is mocked in the App flows: `fetch` is replaced by a
 * small backend, so the real client builds the real request.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import App from './App';
import {
  ApiError,
  DETAILED_AUDIT_FALLBACK_FILENAME,
  downloadDetailedUnderwriteAuditWorkbook,
} from './api';
import capitalEconomicsFixture from './capitalEconomicsFixture.json';
import { DEFAULT_FORM_VALUES, buildAcquisitionRequest } from './convert';
import { clone } from './leaseLevelDealFixture';
import type { AcquisitionResults, Deal, DetailedAcquisitionResults } from './types';

vi.setConfig({ testTimeout: 30_000, hookTimeout: 30_000 });

const EXPORT_ITEM = 'Export Excel audit (.xlsx)';
const DETAILED = capitalEconomicsFixture.detailed.v5_mixed;
const DETAILED_RESULTS = DETAILED.response as unknown as DetailedAcquisitionResults;
const QUICK_RESULTS = capitalEconomicsFixture.quick.v5_mixed.response as unknown as AcquisitionResults;

const FILENAME = 'Harbor Point - Detailed Underwrite Audit.xlsx';
const DISPOSITION =
  `attachment; filename="${FILENAME}"; ` +
  `filename*=UTF-8''Harbor%20Point%20-%20Detailed%20Underwrite%20Audit.xlsx`;
const QUICK_FILENAME = 'Quay Street - Quick Underwrite Audit.xlsx';
const QUICK_DISPOSITION =
  `attachment; filename="${QUICK_FILENAME}"; ` +
  `filename*=UTF-8''Quay%20Street%20-%20Quick%20Underwrite%20Audit.xlsx`;

const DETAILED_PATH = '/deals/detailed-1/exports/detailed-underwrite.xlsx';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
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

/** Records every URL the client asks for, so the request it built can be read
 * back without mocking `api.ts` itself. */
function recordingFetch(response: () => Response): { urls: string[] } {
  const urls: string[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: RequestInfo | URL) => {
      urls.push(String(url));
      return response();
    }),
  );
  return { urls };
}

describe('the Detailed client', () => {
  it('requests the Detailed endpoint and returns the server filename', async () => {
    const recorded = recordingFetch(() => binaryReply(200, { 'Content-Disposition': DISPOSITION }));
    const { filename } = await downloadDetailedUnderwriteAuditWorkbook('detailed-1');
    expect(filename).toBe(FILENAME);
    expect(recorded.urls[0]).toContain(DETAILED_PATH);
  });

  it('encodes a deal id that would otherwise change the path', async () => {
    const recorded = recordingFetch(() => binaryReply(200, { 'Content-Disposition': DISPOSITION }));
    await downloadDetailedUnderwriteAuditWorkbook('a/b?c');
    expect(recorded.urls[0]).toContain('/deals/a%2Fb%3Fc/exports/detailed-underwrite.xlsx');
  });

  it('falls back to a generic filename when the header carries none', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => binaryReply(200, {})));
    const { filename } = await downloadDetailedUnderwriteAuditWorkbook('detailed-1');
    expect(filename).toBe(DETAILED_AUDIT_FALLBACK_FILENAME);
  });

  it('surfaces the server refusal message verbatim', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        binaryReply(409, {}, {
          detail: {
            code: 'analysis_stale',
            message: 'The saved analysis no longer matches the saved inputs.',
          },
        }),
      ),
    );
    await expect(downloadDetailedUnderwriteAuditWorkbook('detailed-1')).rejects.toThrow(
      'The saved analysis no longer matches the saved inputs.',
    );
  });

  it('reports an unreachable backend rather than a silent failure', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('network down');
    }));
    await expect(downloadDetailedUnderwriteAuditWorkbook('detailed-1')).rejects.toBeInstanceOf(ApiError);
  });

  it('keeps a generic message when the refusal body is not JSON', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => binaryReply(500, {})));
    await expect(downloadDetailedUnderwriteAuditWorkbook('detailed-1')).rejects.toThrow(
      'The audit workbook could not be exported.',
    );
  });
});

// =============================================================================
// The App flows
// =============================================================================

interface Recorded {
  method: string;
  path: string;
}

let requests: Recorded[] = [];
let deals: Deal[] = [];
let exportReply: () => Response = () => binaryReply(200, { 'Content-Disposition': DISPOSITION });

function emptyDeal(overrides: Partial<Deal>): Deal {
  return {
    id: 'deal',
    name: 'Deal',
    operating_mode: 'quick',
    inputs: null,
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
    analysis_snapshot: null,
    ai_snapshot: null,
    one_way_sensitivity_snapshot: null,
    two_way_sensitivity_snapshot: null,
    created_at: '2026-09-12T09:00:00+00:00',
    updated_at: '2026-09-12T09:00:00+00:00',
    ...overrides,
  };
}

function detailedDeal(overrides: Partial<Deal> = {}): Deal {
  return emptyDeal({
    id: 'detailed-1',
    name: 'Harbor Point',
    operating_mode: 'detailed',
    terms: clone(DETAILED.request.terms) as Deal['terms'],
    detailed_operating_inputs: clone(
      DETAILED.request.detailed_operating_inputs,
    ) as Deal['detailed_operating_inputs'],
    analysis_snapshot: clone(DETAILED_RESULTS) as unknown as Deal['analysis_snapshot'],
    ...overrides,
  });
}

function quickDeal(overrides: Partial<Deal> = {}): Deal {
  return emptyDeal({
    id: 'quick-1',
    name: 'Quay Street',
    operating_mode: 'quick',
    inputs: buildAcquisitionRequest(DEFAULT_FORM_VALUES),
    analysis_snapshot: clone(QUICK_RESULTS) as unknown as Deal['analysis_snapshot'],
    ...overrides,
  });
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
  if (path.endsWith('/exports/detailed-underwrite.xlsx')) {
    return exportReply();
  }
  if (path.endsWith('/exports/quick-underwrite.xlsx')) {
    return binaryReply(200, { 'Content-Disposition': QUICK_DISPOSITION });
  }
  const single = /^\/deals\/([^/]+)$/.exec(path);
  if (method === 'GET' && single !== null) {
    const deal = deals.find((candidate) => candidate.id === decodeURIComponent(single[1]));
    return deal ? reply(200, deal) : reply(404, { detail: 'not found' });
  }
  return reply(500, {});
}

const exportsTo = (suffix: string) => requests.filter((request) => request.path.endsWith(suffix));

let clicked: { href: string; download: string }[] = [];

beforeEach(() => {
  requests = [];
  clicked = [];
  deals = [detailedDeal()];
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

async function launchAndOpen(name: string): Promise<User> {
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

describe('exporting from the Detailed workspace', () => {
  it('downloads the saved, analysed Detailed deal through the Detailed endpoint', async () => {
    const user = await launchAndOpen('Harbor Point');
    const item = await exportItem(user);
    expect(item.disabled).toBe(false);
    await user.click(item);
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe(`Exported ${FILENAME}`));
    expect(exportsTo('/exports/detailed-underwrite.xlsx')).toEqual([
      { method: 'GET', path: DETAILED_PATH },
    ]);
    expect(exportsTo('/exports/quick-underwrite.xlsx')).toEqual([]);
    expect(clicked).toEqual([{ href: 'blob:workbook', download: FILENAME }]);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:workbook');
    // Exporting writes nothing.
    expect(requests.filter((request) => request.method !== 'GET')).toEqual([]);
  });

  it('shows the server refusal verbatim as an alert', async () => {
    exportReply = () =>
      binaryReply(409, {}, {
        detail: {
          code: 'analysis_stale',
          message: 'The saved analysis no longer matches the saved inputs.',
        },
      });
    const user = await launchAndOpen('Harbor Point');
    await user.click(await exportItem(user));
    await waitFor(() =>
      expect(screen.getByRole('alert').textContent).toBe(
        'The saved analysis no longer matches the saved inputs.',
      ),
    );
  });

  it('drops the outcome line once the deal no longer matches what was exported', async () => {
    const user = await launchAndOpen('Harbor Point');
    await user.click(await exportItem(user));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe(`Exported ${FILENAME}`));
    await user.type(screen.getByLabelText('Deal Name'), ' II');
    expect(screen.queryByText(`Exported ${FILENAME}`)).toBeNull();
  });

  it('refuses unsaved changes and says what to do, sending nothing', async () => {
    const user = await launchAndOpen('Harbor Point');
    await user.type(screen.getByLabelText('Deal Name'), ' II');
    const item = await exportItem(user);
    expect(item.disabled).toBe(true);
    expect(document.getElementById('workbook-export-note')?.textContent).toBe(
      'Unsaved changes are not exported. Save the Deal and analyze the saved inputs first.',
    );
    fireEvent.click(item);
    expect(exportsTo('/exports/detailed-underwrite.xlsx')).toEqual([]);
  });

  it('refuses a saved Detailed deal with no analysis', async () => {
    deals = [detailedDeal({ analysis_snapshot: null })];
    const user = await launchAndOpen('Harbor Point');
    const item = await exportItem(user);
    expect(item.disabled).toBe(true);
    expect(document.getElementById('workbook-export-note')?.textContent).toBe(
      'Analyze the saved inputs first. The workbook contains only a saved, current analysis.',
    );
    fireEvent.click(item);
    expect(exportsTo('/exports/detailed-underwrite.xlsx')).toEqual([]);
  });

  it('is reachable and operable from the keyboard', async () => {
    const user = await launchAndOpen('Harbor Point');
    const trigger = screen.getByRole('button', { name: 'More deal actions' });
    trigger.focus();
    await user.keyboard('{Enter}');
    const item = within(screen.getByRole('menu')).getByRole('menuitem', { name: EXPORT_ITEM });
    item.focus();
    await user.keyboard('{Enter}');
    await waitFor(() => expect(exportsTo('/exports/detailed-underwrite.xlsx')).toHaveLength(1));
  });
});

describe('mode routing', () => {
  it('sends a Quick deal to the Quick endpoint, never the Detailed one', async () => {
    deals = [quickDeal()];
    const user = await launchAndOpen('Quay Street');
    await user.click(await exportItem(user));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe(`Exported ${QUICK_FILENAME}`));
    expect(exportsTo('/exports/quick-underwrite.xlsx')).toEqual([
      { method: 'GET', path: '/deals/quick-1/exports/quick-underwrite.xlsx' },
    ]);
    expect(exportsTo('/exports/detailed-underwrite.xlsx')).toEqual([]);
  });

  it('keeps each mode on its own endpoint when both deals are opened in turn', async () => {
    deals = [detailedDeal(), quickDeal()];
    const user = await launchAndOpen('Harbor Point');
    await user.click(await exportItem(user));
    await waitFor(() => expect(exportsTo('/exports/detailed-underwrite.xlsx')).toHaveLength(1));

    const sidebar = document.querySelector('.sidebar-deal-list') as HTMLElement;
    await user.click(await within(sidebar).findByText('Quay Street'));
    await waitFor(() => expect(screen.getByDisplayValue('Quay Street')).toBeTruthy());
    await user.click(await exportItem(user));
    await waitFor(() => expect(exportsTo('/exports/quick-underwrite.xlsx')).toHaveLength(1));

    expect(exportsTo('/exports/detailed-underwrite.xlsx')).toHaveLength(1);
    expect(exportsTo('/exports/quick-underwrite.xlsx')).toHaveLength(1);
  });

  it("does not offer a Detailed deal's export message on a Quick deal", async () => {
    deals = [detailedDeal(), quickDeal()];
    const user = await launchAndOpen('Harbor Point');
    await user.click(await exportItem(user));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe(`Exported ${FILENAME}`));

    const sidebar = document.querySelector('.sidebar-deal-list') as HTMLElement;
    await user.click(await within(sidebar).findByText('Quay Street'));
    await waitFor(() => expect(screen.getByDisplayValue('Quay Street')).toBeTruthy());
    expect(screen.queryByText(`Exported ${FILENAME}`)).toBeNull();
  });
});

describe('Lease-Level', () => {
  it('shows the action disabled with an honest, mode-specific explanation', async () => {
    const user = userEvent.setup({ delay: null });
    render(<App />);
    await waitFor(() => expect(document.querySelector('.sidebar-deal-list')).not.toBeNull());
    const modes = screen.getByRole('tablist', { name: 'Underwriting Mode' });
    await user.click(within(modes).getByRole('tab', { name: /Lease-Level/ }));
    await waitFor(() =>
      expect(screen.getByRole('tablist', { name: 'Lease-Level sections' })).toBeTruthy(),
    );

    const item = await exportItem(user);
    expect(item.disabled).toBe(true);
    expect(document.getElementById('workbook-export-note')?.textContent).toBe(
      'The Excel audit workbook is available for Quick and Detailed Underwrite Deals. ' +
        'Lease-Level Deals are not exported yet.',
    );
    fireEvent.click(item);
    expect(exportsTo('.xlsx')).toEqual([]);
  });
});
