/**
 * Phase 7 Gate P7.3 -- the Scenario client in `api.ts`.
 *
 * Each function is driven against a stubbed `fetch` and read back from the
 * wire: the URL, the method, the exact body, and how every refusal arrives. The
 * client computes nothing, so there is nothing numeric to check here beyond
 * "what the backend returned is what the caller gets".
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  analyzeInvestmentScenario,
  ApiError,
  createDealScenario,
  deleteInvestmentScenario,
  fetchScenarioTargetCatalog,
  fetchScenarioVariantFingerprint,
  getInvestmentScenario,
  listDealScenarios,
  ScenarioApiError,
  updateInvestmentScenario,
} from './api';
import type { InvestmentScenario, ScenarioDraft } from './scenarioTypes';

const BASE = 'http://127.0.0.1:8000';

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
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

const DRAFT: ScenarioDraft = {
  name: 'Downside',
  description: null,
  overrides: [{ unit_id: 'deal-1', target: 'exit_cap_rate', operation: 'add', value: 0.005 }],
};

const RECORD: InvestmentScenario = {
  investment_id: 'inv-1',
  scenario: { scenario_id: 'sc-1', ...DRAFT },
  created_at: '2026-09-13T00:00:00+00:00',
  updated_at: '2026-09-13T00:00:00+00:00',
};

function sentBody(fetchMock: ReturnType<typeof stubFetch>): unknown {
  const init = fetchMock.mock.calls[0][1];
  return JSON.parse(String(init?.body));
}

describe('the Scenario client -- requests', () => {
  it('lists a standalone deal as having no Investment and no Scenarios', async () => {
    const fetchMock = stubFetch(
      jsonResponse(200, { deal_id: 'deal-1', investment_id: null, scenarios: [] }),
    );
    const listed = await listDealScenarios('deal-1');
    expect(fetchMock).toHaveBeenCalledWith(`${BASE}/deals/deal-1/scenarios`, { method: 'GET' });
    expect(listed).toEqual({ deal_id: 'deal-1', investment_id: null, scenarios: [] });
  });

  it('creates a Scenario on the deal route with exactly name, description and overrides', async () => {
    const fetchMock = stubFetch(jsonResponse(200, RECORD));
    const created = await createDealScenario('deal-1', {
      ...DRAFT,
      // An extra key on the caller's object never reaches the wire.
      ...({ scenario_id: 'forged' } as object),
    } as ScenarioDraft);
    expect(fetchMock.mock.calls[0][0]).toBe(`${BASE}/deals/deal-1/scenarios`);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    expect(sentBody(fetchMock)).toEqual({
      name: 'Downside',
      description: null,
      overrides: [{ unit_id: 'deal-1', target: 'exit_cap_rate', operation: 'add', value: 0.005 }],
    });
    expect(created).toEqual(RECORD);
  });

  it('reads one Scenario through the Investment that owns it', async () => {
    const fetchMock = stubFetch(jsonResponse(200, RECORD));
    expect(await getInvestmentScenario('inv-1', 'sc-1')).toEqual(RECORD);
    expect(fetchMock).toHaveBeenCalledWith(`${BASE}/investments/inv-1/scenarios/sc-1`, {
      method: 'GET',
    });
  });

  it('updates a Scenario with PUT, replacing its whole body', async () => {
    const fetchMock = stubFetch(jsonResponse(200, RECORD));
    await updateInvestmentScenario('inv-1', 'sc-1', { ...DRAFT, description: 'Edited' });
    expect(fetchMock.mock.calls[0][0]).toBe(`${BASE}/investments/inv-1/scenarios/sc-1`);
    expect(fetchMock.mock.calls[0][1]?.method).toBe('PUT');
    expect(sentBody(fetchMock)).toEqual({ ...DRAFT, description: 'Edited' });
  });

  it('deletes a Scenario and reads no body from the 204', async () => {
    const json = vi.fn();
    const fetchMock = stubFetch({ ok: true, status: 204, json } as unknown as Response);
    await expect(deleteInvestmentScenario('inv-1', 'sc-1')).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(`${BASE}/investments/inv-1/scenarios/sc-1`, {
      method: 'DELETE',
    });
    expect(json).not.toHaveBeenCalled();
  });

  it('transports the backend fingerprint without computing one', async () => {
    const fingerprint = {
      investment_id: 'inv-1',
      scenario_id: 'sc-1',
      unit_id: 'deal-1',
      operating_mode: 'quick',
      source_fingerprint: 'abc123',
    };
    const fetchMock = stubFetch(jsonResponse(200, fingerprint));
    expect(await fetchScenarioVariantFingerprint('inv-1', 'sc-1')).toEqual(fingerprint);
    expect(fetchMock).toHaveBeenCalledWith(`${BASE}/investments/inv-1/scenarios/sc-1/fingerprint`, {
      method: 'GET',
    });
  });

  it('requests a Scenario analysis with a bodiless POST and returns it unchanged', async () => {
    const analysis = { investment_id: 'inv-1', scenario_id: 'sc-1', cache_status: 'miss' };
    const fetchMock = stubFetch(jsonResponse(200, analysis));
    expect(await analyzeInvestmentScenario('inv-1', 'sc-1')).toEqual(analysis);
    expect(fetchMock).toHaveBeenCalledWith(`${BASE}/investments/inv-1/scenarios/sc-1/analysis`, {
      method: 'POST',
    });
  });

  it('reads the target catalog from its read-only route', async () => {
    const catalog = { quick: [], detailed: [], lease_level: [] };
    const fetchMock = stubFetch(jsonResponse(200, catalog));
    expect(await fetchScenarioTargetCatalog()).toEqual(catalog);
    expect(fetchMock).toHaveBeenCalledWith(`${BASE}/scenario-targets`, { method: 'GET' });
  });

  it('encodes every id it places in a path', async () => {
    const fetchMock = stubFetch(jsonResponse(200, RECORD));
    await getInvestmentScenario('inv/1', 'sc 1');
    expect(fetchMock.mock.calls[0][0]).toBe(`${BASE}/investments/inv%2F1/scenarios/sc%201`);
  });
});

describe('the Scenario client -- refusals', () => {
  it('surfaces a P7.1 422 as structured issues, in the backend order and words', async () => {
    const issues = [
      {
        stage: 'scenario',
        code: 'invalid_scenario_name',
        message: "name '' must be a nonblank string.",
        target: null,
        unit_id: null,
        field: null,
        source_code: null,
      },
      {
        stage: 'scenario',
        code: 'operation_not_allowed',
        message: "exit_cap_rate: operation 'cap_at' is not allowed; allowed operations: set, add, scale.",
        target: 'exit_cap_rate',
        unit_id: 'deal-1',
        field: null,
        source_code: null,
      },
    ];
    stubFetch(jsonResponse(422, { detail: issues }));
    const error = await createDealScenario('deal-1', DRAFT).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ScenarioApiError);
    expect(error).toBeInstanceOf(ApiError);
    const refusal = error as ScenarioApiError;
    expect(refusal.status).toBe(422);
    expect(refusal.scenarioIssues).toEqual(issues);
    expect(refusal.reasons).toEqual([issues[0].message, issues[1].message]);
    expect(refusal.message).toBe(`${issues[0].message} ${issues[1].message}`);
  });

  it('surfaces a Lease-Level refusal of a variant in its own vocabulary', async () => {
    const leaseIssue = {
      code: 'non_positive_exit_noi',
      path: 'terms.exit_cap_rate',
      message: 'The forward exit NOI must be positive.',
      severity: 'error',
    };
    stubFetch(jsonResponse(422, { detail: [leaseIssue] }));
    const error = (await analyzeInvestmentScenario('inv-1', 'sc-1').catch(
      (caught: unknown) => caught,
    )) as ScenarioApiError;
    expect(error.status).toBe(422);
    expect(error.leaseIssues).toEqual([leaseIssue]);
    expect(error.scenarioIssues).toEqual([]);
    expect(error.reasons).toEqual(['The forward exit NOI must be positive.']);
  });

  it('says a 404 in the analyst’s words, never with internal ids', async () => {
    stubFetch(jsonResponse(404, { detail: "No scenario 'sc-1' belongs to investment 'inv-1'." }));
    const error = (await getInvestmentScenario('inv-1', 'sc-1').catch(
      (caught: unknown) => caught,
    )) as ScenarioApiError;
    expect(error.status).toBe(404);
    expect(error.message).toBe('That scenario or deal could not be found. It may have been deleted.');
    expect(error.message).not.toContain('inv-1');
  });

  it('keeps a string refusal verbatim', async () => {
    stubFetch(jsonResponse(409, { detail: 'A visible Investment is not managed here.' }));
    const error = (await deleteInvestmentScenario('inv-1', 'sc-1').catch(
      (caught: unknown) => caught,
    )) as ScenarioApiError;
    expect(error.status).toBe(409);
    expect(error.message).toBe('A visible Investment is not managed here.');
  });

  it('names the failed request, with its status, when no reason came back', async () => {
    stubFetch(jsonResponse(500, null));
    const error = (await analyzeInvestmentScenario('inv-1', 'sc-1').catch(
      (caught: unknown) => caught,
    )) as ScenarioApiError;
    expect(error.status).toBe(500);
    expect(error.message).toBe('The scenario analysis could not be completed (HTTP 500).');
  });

  it('reports an unreachable API as the shared network error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    const error = await listDealScenarios('deal-1').catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).not.toBeInstanceOf(ScenarioApiError);
    expect((error as ApiError).message).toContain('Could not reach the Anchor API');
  });
});
