/**
 * Phase 7 Gate P7.6 -- the visible Investment client, request by request.
 *
 * Each function is called against a stubbed `fetch` and the exact method, URL
 * and body it puts on the wire are read back: the Investment-scoped Strategy
 * and Scenario routes (never the Deal-scoped ones), the consolidated matrix
 * route (never the one-unit one), and the one DELETE that removes a Unit and
 * states the resulting price. Refusals are parsed by shape, every backend
 * message kept.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import * as api from './api';

const BASE = 'http://127.0.0.1:8000';

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubFetch(response: { ok: boolean; status: number; body: unknown }) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: response.ok,
    status: response.status,
    json: async () => response.body,
  } as Response);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function sent(fetchMock: ReturnType<typeof vi.fn>) {
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  return {
    url,
    method: init.method,
    body: init.body === undefined ? undefined : (JSON.parse(init.body as string) as Record<string, unknown>),
  };
}

const PLAN = { capital_items: [], owner_expense_items: [] };
const COST = {
  cost_id: 'cost-1',
  description: 'Portfolio legal',
  category: 'legal' as const,
  amount: 125_000,
  model_month: 0,
};

describe('the visible Investment lifecycle', () => {
  it('lists and reads visible Investments', async () => {
    let fetchMock = stubFetch({ ok: true, status: 200, body: [] });
    await api.listVisibleInvestments();
    expect(sent(fetchMock)).toMatchObject({ url: `${BASE}/investments`, method: 'GET' });
    vi.unstubAllGlobals();
    fetchMock = stubFetch({ ok: true, status: 200, body: {} });
    await api.getVisibleInvestment('inv 1');
    expect(sent(fetchMock)).toMatchObject({ url: `${BASE}/investments/inv%201/details`, method: 'GET' });
  });

  it('creates with exactly the five keys, each Unit and cost exact', async () => {
    const fetchMock = stubFetch({ ok: true, status: 200, body: {} });
    await api.createVisibleInvestment({
      name: 'Harbor Portfolio',
      transaction_price: 45_000_000,
      units: [{ unit_id: 'deal-a', label: 'Retail', unit_kind: 'component' }],
      business_plan: PLAN,
      transaction_costs: [COST],
    });
    const request = sent(fetchMock);
    expect(request.url).toBe(`${BASE}/investments`);
    expect(request.method).toBe('POST');
    expect(request.body).toEqual({
      name: 'Harbor Portfolio',
      transaction_price: 45_000_000,
      units: [{ unit_id: 'deal-a', label: 'Retail', unit_kind: 'component' }],
      business_plan: PLAN,
      transaction_costs: [COST],
    });
  });

  it('promotes the hidden wrapper itself, on its own id', async () => {
    const fetchMock = stubFetch({ ok: true, status: 200, body: {} });
    await api.promoteHiddenInvestment('wrapper-7', {
      name: 'Promoted',
      transaction_price: 12_000_000,
      units: [{ unit_id: 'deal-a', label: null, unit_kind: 'property' }],
      business_plan: PLAN,
      transaction_costs: [],
    });
    const request = sent(fetchMock);
    expect(request.url).toBe(`${BASE}/investments/wrapper-7/promote`);
    expect(request.method).toBe('POST');
    expect(Object.keys(request.body ?? {})).toEqual([
      'name',
      'transaction_price',
      'units',
      'business_plan',
      'transaction_costs',
    ]);
  });

  it('replaces the four details together in one PUT', async () => {
    const fetchMock = stubFetch({ ok: true, status: 200, body: {} });
    await api.updateVisibleInvestmentDetails('inv-1', {
      name: 'Renamed',
      transaction_price: 45_500_000,
      business_plan: PLAN,
      transaction_costs: [COST],
    });
    const request = sent(fetchMock);
    expect(request).toMatchObject({ url: `${BASE}/investments/inv-1/details`, method: 'PUT' });
    expect(request.body).toEqual({
      name: 'Renamed',
      transaction_price: 45_500_000,
      business_plan: PLAN,
      transaction_costs: [COST],
    });
  });

  it('deletes the Investment itself', async () => {
    const fetchMock = stubFetch({ ok: true, status: 204, body: null });
    await api.deleteVisibleInvestment('inv-1');
    expect(sent(fetchMock)).toMatchObject({ url: `${BASE}/investments/inv-1`, method: 'DELETE' });
  });
});

describe('Units', () => {
  it('adds a Unit with the analyst’s resulting price in the same request', async () => {
    const fetchMock = stubFetch({ ok: true, status: 200, body: {} });
    await api.addInvestmentUnit('inv-1', {
      unit_id: 'deal-d',
      label: null,
      unit_kind: 'property',
      transaction_price: 57_000_000,
    });
    const request = sent(fetchMock);
    expect(request).toMatchObject({ url: `${BASE}/investments/inv-1/units`, method: 'POST' });
    expect(request.body).toEqual({ unit_id: 'deal-d', label: null, unit_kind: 'property', transaction_price: 57_000_000 });
  });

  it('changes display metadata only', async () => {
    const fetchMock = stubFetch({ ok: true, status: 200, body: {} });
    await api.updateInvestmentUnitDisplay('inv-1', 'deal-a', { label: 'North', unit_kind: 'phase', ordinal: 3 });
    const request = sent(fetchMock);
    expect(request).toMatchObject({ url: `${BASE}/investments/inv-1/units/deal-a`, method: 'PUT' });
    expect(request.body).toEqual({ label: 'North', unit_kind: 'phase', ordinal: 3 });
  });

  it('removes a Unit and restates the price in ONE DELETE', async () => {
    const fetchMock = stubFetch({ ok: true, status: 200, body: {} });
    await api.removeInvestmentUnit('inv-1', 'deal-b', 33_000_000);
    const request = sent(fetchMock);
    expect(request.method).toBe('DELETE');
    expect(request.url).toBe(`${BASE}/investments/inv-1/units/deal-b?transaction_price=33000000`);
    expect(request.body).toBeUndefined();
  });
});

describe('analysis and the decision tools of a visible Investment', () => {
  it('analyses the Base variant on the consolidated route', async () => {
    const fetchMock = stubFetch({ ok: true, status: 200, body: {} });
    await api.analyzeInvestmentVariant('inv-1', 'base', 'base');
    expect(sent(fetchMock)).toMatchObject({
      url: `${BASE}/investments/inv-1/investment-variants/base/base/analysis`,
      method: 'POST',
    });
  });

  it('runs the consolidated Decision Matrix, never the one-unit route', async () => {
    const fetchMock = stubFetch({ ok: true, status: 200, body: {} });
    await api.analyzeInvestmentDecisionMatrix('inv-1');
    const request = sent(fetchMock);
    expect(request).toMatchObject({ url: `${BASE}/investments/inv-1/investment-decision-matrix`, method: 'POST' });
    expect(request.url).not.toMatch(/\/decision-matrix$/);
  });

  it('lists and creates Scenarios on the Investment route', async () => {
    let fetchMock = stubFetch({ ok: true, status: 200, body: [] });
    await api.listInvestmentScenarios('inv-1');
    expect(sent(fetchMock)).toMatchObject({ url: `${BASE}/investments/inv-1/scenarios`, method: 'GET' });
    vi.unstubAllGlobals();
    fetchMock = stubFetch({ ok: true, status: 200, body: {} });
    await api.createInvestmentScenario('inv-1', {
      name: 'Downside',
      description: null,
      overrides: [{ unit_id: 'deal-a', target: 'exit_cap_rate', operation: 'add', value: 0.005 }],
    });
    const request = sent(fetchMock);
    expect(request).toMatchObject({ url: `${BASE}/investments/inv-1/scenarios`, method: 'POST' });
    expect(request.url).not.toContain('/deals/');
  });

  it('lists and saves Strategies on the Investment routes: POST new, PUT existing', async () => {
    let fetchMock = stubFetch({ ok: true, status: 200, body: [] });
    await api.listInvestmentStrategies('inv-1');
    expect(sent(fetchMock)).toMatchObject({ url: `${BASE}/investments/inv-1/strategies`, method: 'GET' });
    const draft = { name: 'Recap', description: null, overlays: [] };
    vi.unstubAllGlobals();
    fetchMock = stubFetch({ ok: true, status: 200, body: {} });
    await api.saveInvestmentStrategy('inv-1', null, draft);
    expect(sent(fetchMock)).toMatchObject({ url: `${BASE}/investments/inv-1/strategies`, method: 'POST' });
    vi.unstubAllGlobals();
    fetchMock = stubFetch({ ok: true, status: 200, body: {} });
    await api.saveInvestmentStrategy('inv-1', 'st-9', draft);
    const request = sent(fetchMock);
    expect(request).toMatchObject({ url: `${BASE}/investments/inv-1/strategies/st-9`, method: 'PUT' });
    expect(request.body).toEqual(draft);
  });
});

describe('refusals keep the backend’s words and structure', () => {
  it('reads Investment issues, each naming its Unit', async () => {
    stubFetch({
      ok: false,
      status: 422,
      body: {
        detail: [
          {
            code: 'allocation_mismatch',
            message: 'The Units’ allocated purchase prices (deal-a: 10, deal-b: 20) sum to 30…',
            unit_id: null,
            field: 'transaction_price',
            source_code: null,
          },
        ],
      },
    });
    const error = await api
      .createVisibleInvestment({ name: 'x', transaction_price: 1, units: [], business_plan: PLAN, transaction_costs: [] })
      .catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(api.InvestmentApiError);
    const refusal = error as api.InvestmentApiError;
    expect(refusal.status).toBe(422);
    expect(refusal.investmentIssues).toHaveLength(1);
    expect(refusal.investmentIssues[0].code).toBe('allocation_mismatch');
    expect(refusal.variantIssues).toEqual([]);
  });

  it('reads a 409 structure refusal as its one sentence', async () => {
    stubFetch({
      ok: false,
      status: 409,
      body: { detail: "Unit 'deal-b' is still addressed by strategy 'st-1'. Remove those overrides and overlays first." },
    });
    const error = (await api.removeInvestmentUnit('inv-1', 'deal-b', 1).catch((caught: unknown) => caught)) as api.InvestmentApiError;
    expect(error.status).toBe(409);
    expect(error.reasons).toEqual([
      "Unit 'deal-b' is still addressed by strategy 'st-1'. Remove those overrides and overlays first.",
    ]);
  });

  it('reads variant issues from a consolidated analysis refusal', async () => {
    stubFetch({
      ok: false,
      status: 422,
      body: {
        detail: [
          { source: 'investment', code: 'hold_period_mismatch', message: 'The Units’ hold periods differ.', unit_id: null, field: 'hold_period' },
        ],
      },
    });
    const error = (await api.analyzeInvestmentVariant('inv-1', 'base', 'base').catch((caught: unknown) => caught)) as api.InvestmentApiError;
    expect(error.variantIssues).toHaveLength(1);
    expect(error.investmentIssues).toEqual([]);
  });

  it('keeps which Business Plan overlay a Strategy refusal names', async () => {
    stubFetch({
      ok: false,
      status: 422,
      body: {
        detail: [
          { code: 'invalid_month', path: 'overlays[2].content.capital_items[0].month', message: 'month must be >= 0' },
        ],
      },
    });
    const error = (await api
      .saveInvestmentStrategy('inv-1', null, { name: 'x', description: null, overlays: [] })
      .catch((caught: unknown) => caught)) as api.InvestmentStrategyApiError;
    expect(error).toBeInstanceOf(api.StrategyApiError);
    expect(error.planIssues).toEqual([
      { code: 'invalid_month', path: 'business_plan.capital_items[0].month', message: 'month must be >= 0' },
    ]);
    expect(error.planIssueOverlays).toEqual([2]);
  });
});
