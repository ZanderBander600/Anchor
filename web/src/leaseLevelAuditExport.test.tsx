/**
 * Excel Export 3 -- the Lease-Level Underwrite audit-workbook action.
 *
 * Two things are tested, and the second is the important one.
 *
 * First, Lease-Level's own eligibility. It differs from Quick's and
 * Detailed's on purpose: a Lease-Level Deal persists no analysis snapshot, so
 * the action waits for the Deal to be *saved and clean* and not for a current
 * in-browser result. The server re-runs the authoritative analysis over the
 * saved inputs it reads.
 *
 * Second, **mode isolation**. Three modes now each have their own endpoint,
 * and each must call only its own. The guard below opens each mode in turn in
 * one app and asserts the exact set of export requests made -- so a handler
 * reading another workspace's deal id, dirty flag or result would send the
 * wrong request and fail here rather than silently exporting the wrong Deal.
 *
 * Nothing in `api.ts` is mocked in the App flows: `fetch` is replaced by a
 * small backend, so the real client builds the real request.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import App from './App';
import {
  ApiError,
  LEASE_LEVEL_AUDIT_FALLBACK_FILENAME,
  downloadLeaseLevelAuditWorkbook,
} from './api';
import capitalEconomicsFixture from './capitalEconomicsFixture.json';
import { DEFAULT_FORM_VALUES, buildAcquisitionRequest } from './convert';
import { clone, makeDeal } from './leaseLevelDealFixture';
import type { AcquisitionResults, Deal, DetailedAcquisitionResults } from './types';

vi.setConfig({ testTimeout: 30_000, hookTimeout: 30_000 });

const EXPORT_ITEM = 'Export Excel audit (.xlsx)';

const DETAILED = capitalEconomicsFixture.detailed.v5_mixed;
const DETAILED_RESULTS = DETAILED.response as unknown as DetailedAcquisitionResults;
const QUICK_RESULTS = capitalEconomicsFixture.quick.v5_mixed.response as unknown as AcquisitionResults;

const FILENAME = 'Rivermark Center - Lease-Level Underwrite Audit.xlsx';
const DISPOSITION =
  `attachment; filename="${FILENAME}"; ` +
  `filename*=UTF-8''Rivermark%20Center%20-%20Lease-Level%20Underwrite%20Audit.xlsx`;

const LEASE_LEVEL_SUFFIX = '/exports/lease-level.xlsx';
const DETAILED_SUFFIX = '/exports/detailed-underwrite.xlsx';
const QUICK_SUFFIX = '/exports/quick-underwrite.xlsx';

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

describe('the Lease-Level client', () => {
  it('requests the Lease-Level endpoint and returns the server filename', async () => {
    const recorded = recordingFetch(() => binaryReply(200, { 'Content-Disposition': DISPOSITION }));
    const { filename } = await downloadLeaseLevelAuditWorkbook('lease-1');
    expect(filename).toBe(FILENAME);
    expect(recorded.urls[0]).toContain(`/deals/lease-1${LEASE_LEVEL_SUFFIX}`);
  });

  it('encodes a deal id that would otherwise change the path', async () => {
    const recorded = recordingFetch(() => binaryReply(200, { 'Content-Disposition': DISPOSITION }));
    await downloadLeaseLevelAuditWorkbook('a/b?c');
    expect(recorded.urls[0]).toContain(`/deals/a%2Fb%3Fc${LEASE_LEVEL_SUFFIX}`);
  });

  it('falls back to a generic filename when the header carries none', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => binaryReply(200, {})));
    const { filename } = await downloadLeaseLevelAuditWorkbook('lease-1');
    expect(filename).toBe(LEASE_LEVEL_AUDIT_FALLBACK_FILENAME);
  });

  it('surfaces a Lease-Level refusal message verbatim', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        binaryReply(422, {}, {
          detail: {
            code: 'terminal_value_not_capitalizable',
            message: 'The forward exit NOI is not positive, so the sale cannot be valued at a cap rate.',
          },
        }),
      ),
    );
    await expect(downloadLeaseLevelAuditWorkbook('lease-1')).rejects.toThrow(
      'The forward exit NOI is not positive, so the sale cannot be valued at a cap rate.',
    );
  });

  it('reports an unreachable backend rather than a silent failure', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('network down');
    }));
    await expect(downloadLeaseLevelAuditWorkbook('lease-1')).rejects.toBeInstanceOf(ApiError);
  });

  it('keeps a generic message when the refusal body is not JSON', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => binaryReply(500, {})));
    await expect(downloadLeaseLevelAuditWorkbook('lease-1')).rejects.toThrow(
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
    asset_type: 'office',
    asset_subtype: null,
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

function leaseLevelDeal(): Deal {
  return makeDeal('lease-1', 'Rivermark Center');
}

function detailedDeal(): Deal {
  return emptyDeal({
    id: 'detailed-1',
    name: 'Harbor Point',
    operating_mode: 'detailed',
    terms: clone(DETAILED.request.terms) as Deal['terms'],
    detailed_operating_inputs: clone(
      DETAILED.request.detailed_operating_inputs,
    ) as Deal['detailed_operating_inputs'],
    analysis_snapshot: clone(DETAILED_RESULTS) as unknown as Deal['analysis_snapshot'],
  });
}

function quickDeal(): Deal {
  return emptyDeal({
    id: 'quick-1',
    name: 'Quay Street',
    operating_mode: 'quick',
    inputs: buildAcquisitionRequest(DEFAULT_FORM_VALUES),
    analysis_snapshot: clone(QUICK_RESULTS) as unknown as Deal['analysis_snapshot'],
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
  if (path.endsWith(LEASE_LEVEL_SUFFIX)) {
    return exportReply();
  }
  if (path.endsWith(DETAILED_SUFFIX) || path.endsWith(QUICK_SUFFIX)) {
    return binaryReply(200, { 'Content-Disposition': DISPOSITION });
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
  deals = [leaseLevelDeal()];
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

async function launch(): Promise<User> {
  const user = userEvent.setup({ delay: null });
  render(<App />);
  await waitFor(() => {
    expect(document.querySelector('.sidebar-deal-list')).not.toBeNull();
  });
  return user;
}

async function open(user: User, name: string): Promise<void> {
  const sidebar = document.querySelector('.sidebar-deal-list') as HTMLElement;
  await user.click(await within(sidebar).findByText(name));
  await waitFor(() => expect(screen.getByDisplayValue(name)).toBeTruthy());
}

async function exportItem(user: User): Promise<HTMLButtonElement> {
  await user.click(screen.getByRole('button', { name: 'More deal actions' }));
  return within(screen.getByRole('menu')).getByRole('menuitem', { name: EXPORT_ITEM }) as HTMLButtonElement;
}

describe('exporting from the Lease-Level workspace', () => {
  it('downloads a saved, clean Lease-Level deal through the Lease-Level endpoint', async () => {
    const user = await launch();
    await open(user, 'Rivermark Center');
    const item = await exportItem(user);
    expect(item.disabled).toBe(false);
    await user.click(item);
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe(`Exported ${FILENAME}`));
    expect(exportsTo(LEASE_LEVEL_SUFFIX).map((request) => request.method)).toEqual(['GET']);
    expect(clicked).toEqual([{ href: 'blob:workbook', download: FILENAME }]);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:workbook');
    // Exporting writes nothing.
    expect(requests.filter((request) => request.method !== 'GET')).toEqual([]);
  });

  it('exports without waiting for an in-browser analysis, because none is persisted', async () => {
    // The fixture deal is opened and never analysed in this test: Lease-Level
    // stores no snapshot, so there is nothing to wait for and the server
    // analyses the saved state it reads.
    const user = await launch();
    await open(user, 'Rivermark Center');
    const item = await exportItem(user);
    expect(item.disabled).toBe(false);
    expect(item.getAttribute('aria-describedby')).toBeNull();
  });

  it('shows the server refusal verbatim as an alert', async () => {
    exportReply = () =>
      binaryReply(409, {}, {
        detail: {
          code: 'lease_level_inputs_invalid',
          message: 'This Deal’s saved Lease-Level inputs could not be analyzed.',
        },
      });
    const user = await launch();
    await open(user, 'Rivermark Center');
    await user.click(await exportItem(user));
    await waitFor(() =>
      expect(screen.getByRole('alert').textContent).toBe(
        'This Deal’s saved Lease-Level inputs could not be analyzed.',
      ),
    );
    expect(clicked).toEqual([]);
  });

  it('disables the action with a save-first reason on an unsaved Deal', async () => {
    deals = [];
    const user = await launch();
    const item = await exportItem(user);
    expect(item.disabled).toBe(true);
  });
});

// =============================================================================
// Mode isolation
// =============================================================================

describe('mode isolation', () => {
  it('routes each mode to its own endpoint and to no other', async () => {
    deals = [leaseLevelDeal(), detailedDeal(), quickDeal()];
    const user = await launch();

    await open(user, 'Rivermark Center');
    await user.click(await exportItem(user));
    await waitFor(() => expect(exportsTo(LEASE_LEVEL_SUFFIX)).toHaveLength(1));

    await open(user, 'Harbor Point');
    await user.click(await exportItem(user));
    await waitFor(() => expect(exportsTo(DETAILED_SUFFIX)).toHaveLength(1));

    await open(user, 'Quay Street');
    await user.click(await exportItem(user));
    await waitFor(() => expect(exportsTo(QUICK_SUFFIX)).toHaveLength(1));

    // Exactly one request per mode, each to its own path and carrying its own
    // deal id. A handler reading another workspace's id would show up here.
    expect(exportsTo(LEASE_LEVEL_SUFFIX)).toEqual([
      { method: 'GET', path: `/deals/lease-1${LEASE_LEVEL_SUFFIX}` },
    ]);
    expect(exportsTo(DETAILED_SUFFIX)).toEqual([
      { method: 'GET', path: `/deals/detailed-1${DETAILED_SUFFIX}` },
    ]);
    expect(exportsTo(QUICK_SUFFIX)).toEqual([
      { method: 'GET', path: `/deals/quick-1${QUICK_SUFFIX}` },
    ]);
    expect(requests.filter((request) => request.method !== 'GET')).toEqual([]);
  });

  it('never exports a Lease-Level Deal through the Quick or Detailed endpoint', async () => {
    deals = [leaseLevelDeal()];
    const user = await launch();
    await open(user, 'Rivermark Center');
    await user.click(await exportItem(user));
    await waitFor(() => expect(exportsTo(LEASE_LEVEL_SUFFIX)).toHaveLength(1));
    expect(exportsTo(QUICK_SUFFIX)).toEqual([]);
    expect(exportsTo(DETAILED_SUFFIX)).toEqual([]);
  });
});
