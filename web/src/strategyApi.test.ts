/**
 * Phase 7 Gate P7.5 -- the Strategy and Decision Matrix client in `api.ts`.
 *
 * Each function is driven against a stubbed `fetch` and read back from the
 * wire: the URL, the method, the exact body, and how every refusal arrives. The
 * client computes nothing, so what the backend returned is what the caller
 * gets.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  analyzeDecisionMatrix,
  ApiError,
  createDealStrategy,
  deleteInvestmentStrategy,
  fetchStrategyTargetCatalog,
  listDealStrategies,
  StrategyApiError,
  updateInvestmentStrategy,
} from './api';
import type { InvestmentStrategy, StrategyDraft } from './strategyTypes';

const BASE = 'http://127.0.0.1:8000';

function jsonResponse(status: number, body: unknown): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

function stubFetch(response: Response) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    void url;
    void init;
    return response;
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const DRAFT: StrategyDraft = {
  name: 'Renovate',
  description: null,
  overlays: [
    { unit_id: 'deal-1', domain: 'acquisition', content: { purchase_price: 9_000_000, acquisition_cost_pct: 0.02 } },
    { unit_id: 'deal-1', domain: 'business_plan', content: { capital_items: [], owner_expense_items: [] } },
  ],
};

const RECORD: InvestmentStrategy = {
  investment_id: 'inv-1',
  strategy: { strategy_id: 'st-1', ...DRAFT },
  created_at: '2026-09-14T00:00:00+00:00',
  updated_at: '2026-09-14T00:00:00+00:00',
};

function sentBody(fetchMock: ReturnType<typeof stubFetch>): unknown {
  return JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
}

describe('the Strategy client -- requests', () => {
  it('lists a standalone deal as having no Investment and no Strategies', async () => {
    const fetchMock = stubFetch(jsonResponse(200, { deal_id: 'deal-1', investment_id: null, strategies: [] }));
    expect(await listDealStrategies('deal-1')).toEqual({ deal_id: 'deal-1', investment_id: null, strategies: [] });
    expect(fetchMock).toHaveBeenCalledWith(`${BASE}/deals/deal-1/strategies`, { method: 'GET' });
  });

  it('creates on the deal route with exactly name, description and overlays', async () => {
    const fetchMock = stubFetch(jsonResponse(200, RECORD));
    const created = await createDealStrategy('deal-1', {
      ...DRAFT,
      ...({ strategy_id: 'forged', investment_id: 'forged' } as object),
    } as StrategyDraft);
    expect(fetchMock.mock.calls[0][0]).toBe(`${BASE}/deals/deal-1/strategies`);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: 'POST', headers: { 'Content-Type': 'application/json' } });
    expect(sentBody(fetchMock)).toEqual({ name: 'Renovate', description: null, overlays: DRAFT.overlays });
    expect(created).toEqual(RECORD);
  });

  it('updates and deletes through the owning Investment, ids encoded', async () => {
    const update = stubFetch(jsonResponse(200, RECORD));
    await updateInvestmentStrategy('inv/1', 'st 1', DRAFT);
    expect(update.mock.calls[0][0]).toBe(`${BASE}/investments/inv%2F1/strategies/st%201`);
    expect(update.mock.calls[0][1]?.method).toBe('PUT');

    const remove = stubFetch(jsonResponse(204, null));
    await deleteInvestmentStrategy('inv-1', 'st-1');
    expect(remove).toHaveBeenCalledWith(`${BASE}/investments/inv-1/strategies/st-1`, { method: 'DELETE' });
  });

  it('reads the Strategy target catalog', async () => {
    const catalog = { quick: [{ target: 'exit_cap_rate', units: 'decimal rate' }], detailed: [], lease_level: [] };
    const fetchMock = stubFetch(jsonResponse(200, catalog));
    expect(await fetchStrategyTargetCatalog()).toEqual(catalog);
    expect(fetchMock).toHaveBeenCalledWith(`${BASE}/strategy-targets`, { method: 'GET' });
  });

  it('asks for the Decision Matrix once, by POST, and returns the package untouched', async () => {
    const report = { investment_id: 'inv-1', unit_id: 'deal-1', operating_mode: 'quick', matrix: { cells: [] } };
    const fetchMock = stubFetch(jsonResponse(200, report));
    expect(await analyzeDecisionMatrix('inv-1')).toEqual(report);
    expect(fetchMock).toHaveBeenCalledWith(`${BASE}/investments/inv-1/decision-matrix`, { method: 'POST' });
  });
});

describe('the Strategy client -- refusals', () => {
  it('reports a structured Strategy 422 in the validator’s own words', async () => {
    stubFetch(
      jsonResponse(422, {
        detail: [
          {
            stage: 'strategy',
            code: 'incomplete_domain',
            message: 'The financing overlay must state io_period.',
            domain: 'financing',
            unit_id: 'deal-1',
            field: 'io_period',
            target: null,
            source_code: null,
          },
        ],
      }),
    );
    const error = await createDealStrategy('deal-1', DRAFT).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(StrategyApiError);
    const refusal = error as StrategyApiError;
    expect(refusal.status).toBe(422);
    expect(refusal.strategyIssues.map((issue) => [issue.domain, issue.code])).toEqual([['financing', 'incomplete_domain']]);
    expect(refusal.reasons).toEqual(['The financing overlay must state io_period.']);
  });

  it('re-roots a Business Plan overlay refusal at business_plan so its row can be found', async () => {
    stubFetch(
      jsonResponse(422, {
        detail: [
          { code: 'invalid_month', path: 'overlays[1].content.capital_items[0].month', message: 'Month must be 0 or more.' },
          { code: 'invalid_plan', path: 'overlays[1].content', message: 'The plan is invalid.' },
        ],
      }),
    );
    const refusal = (await createDealStrategy('deal-1', DRAFT).catch((caught: unknown) => caught)) as StrategyApiError;
    expect(refusal.planIssues).toEqual([
      { code: 'invalid_month', path: 'business_plan.capital_items[0].month', message: 'Month must be 0 or more.' },
      { code: 'invalid_plan', path: 'business_plan', message: 'The plan is invalid.' },
    ]);
    expect(refusal.strategyIssues).toEqual([]);
  });

  it('never reads a Scenario issue as a Strategy issue', async () => {
    stubFetch(
      jsonResponse(422, {
        detail: [{ stage: 'resolved_inputs', code: 'resolved_input_invalid', message: 'x', target: null, unit_id: null, field: null, source_code: null }],
      }),
    );
    const refusal = (await createDealStrategy('deal-1', DRAFT).catch((caught: unknown) => caught)) as StrategyApiError;
    expect(refusal.strategyIssues).toEqual([]);
    expect(refusal.reasons).toEqual(['x']);
  });

  it('says a 404 in the analyst’s words and a 409 in the backend’s', async () => {
    stubFetch(jsonResponse(404, { detail: "No strategy 'st-1' belongs to investment 'inv-1'." }));
    const missing = (await deleteInvestmentStrategy('inv-1', 'st-1').catch((caught: unknown) => caught)) as StrategyApiError;
    expect(missing.message).toBe('That strategy or deal could not be found. It may have been deleted.');

    stubFetch(jsonResponse(409, { detail: 'The saved underwriting changed while the decision matrix was running. Run it again.' }));
    const conflict = (await analyzeDecisionMatrix('inv-1').catch((caught: unknown) => caught)) as StrategyApiError;
    expect(conflict.status).toBe(409);
    expect(conflict.message).toBe('The saved underwriting changed while the decision matrix was running. Run it again.');
  });

  it('reports an unreachable backend as the one network message', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }));
    const error = await analyzeDecisionMatrix('inv-1').catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toContain('Could not reach the Anchor API');
  });
});
