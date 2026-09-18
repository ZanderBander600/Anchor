/**
 * Phase 7 Gate P7.9 Stage 3 -- the Partnership client in `api.ts`.
 *
 * Each function is driven against a stubbed `fetch` and read back from the
 * wire: the URL, the method, the exact body, and how every refusal arrives. The
 * client computes nothing, so there is nothing numeric to check here beyond
 * "what the backend returned is what the caller gets".
 *
 * The body assertions matter more here than usual. `null` is a **statement** on
 * these routes -- "this owner states no Partnership" -- and a client that sent
 * an omitted key, an empty object or an empty partner list instead would be
 * saying something the backend reads differently, or nothing at all.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  analyzePartnerDecisionMatrix,
  analyzePartnershipVariant,
  listPartnerPerspectives,
  PartnershipError,
  readDealPartnership,
  readInvestmentPartnership,
  readPartnershipVariantFingerprint,
  saveDealPartnership,
  saveInvestmentPartnership,
} from './api';
import type { Partnership } from './partnershipTypes';

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

/** A whole, ratified LP / GP partnership: an 8% SIMPLE preferred hurdle to the
 * LP, a catch-up to the GP, then a residual. Every typed variant carries its
 * `kind`. */
const PARTNERSHIP: Partnership = {
  partners: [
    {
      partner_id: 'lp',
      name: 'Harbor Capital LP',
      role: 'lp',
      investor_class: 'class_a',
      commitment_share: 0.9,
    },
    { partner_id: 'gp', name: 'Sponsor GP', role: 'gp', investor_class: null, commitment_share: 0.1 },
  ],
  contribution_rule: 'pro_rata_by_commitment',
  promote_benchmark: {
    shares: [
      { partner_id: 'lp', share: 0.9 },
      { partner_id: 'gp', share: 0.1 },
    ],
  },
  promote_participant_ids: ['gp'],
  tiers: [
    {
      tier_id: 'tier-1',
      name: 'Preferred Return',
      sequence: 1,
      kind: 'hurdle',
      split: {
        kind: 'explicit',
        shares: [
          { partner_id: 'lp', share: 1 },
          { partner_id: 'gp', share: 0 },
        ],
      },
      hurdle: {
        hurdle_subject: {
          kind: 'partner',
          partner_id: 'lp',
          investor_class: null,
          account: null,
        },
        conditions: [
          {
            kind: 'irr',
            condition_id: 'cond-1',
            rate: 0.08,
            accrual_convention: 'simple',
            simple_distribution_order: 'accrued_return_first',
          },
        ],
        combinator: 'all',
      },
      catch_up: null,
    },
    {
      tier_id: 'tier-2',
      name: 'Catch-Up',
      sequence: 2,
      kind: 'catch_up',
      split: {
        kind: 'explicit',
        shares: [
          { partner_id: 'lp', share: 0 },
          { partner_id: 'gp', share: 1 },
        ],
      },
      hurdle: null,
      catch_up: {
        recipient: { kind: 'partner', partner_id: 'gp', investor_class: null },
        target_profit_share: 0.2,
      },
    },
    {
      tier_id: 'tier-3',
      name: 'Residual',
      sequence: 3,
      kind: 'residual',
      split: { kind: 'pro_rata_by_contribution' },
      hurdle: null,
      catch_up: null,
    },
  ],
};

describe('the persisted Partnership routes', () => {
  it('reads a Deal’s Partnership, and reports null when it states none', async () => {
    const fetchMock = stubFetch(
      jsonResponse(200, { deal_id: 'deal-1', investment_id: null, partnership: null }),
    );
    const payload = await readDealPartnership('deal-1');

    expect(fetchMock).toHaveBeenCalledWith(`${BASE}/deals/deal-1/partnership`, { method: 'GET' });
    expect(payload.partnership).toBeNull();
    expect(payload.investment_id).toBeNull();
  });

  it('saves a Deal’s Partnership whole, under the `partnership` key', async () => {
    const fetchMock = stubFetch(
      jsonResponse(200, {
        deal_id: 'deal-1',
        investment_id: 'inv-1',
        partnership: PARTNERSHIP,
      }),
    );
    const payload = await saveDealPartnership('deal-1', PARTNERSHIP);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/deals/deal-1/partnership`);
    expect(init?.method).toBe('PUT');
    expect(JSON.parse(String(init?.body))).toEqual({ partnership: PARTNERSHIP });
    // Every typed variant keeps its discriminator through the round trip.
    const body = JSON.parse(String(init?.body)) as { partnership: Partnership };
    expect(body.partnership.tiers[0].split?.kind).toBe('explicit');
    expect(body.partnership.tiers[2].split?.kind).toBe('pro_rata_by_contribution');
    expect(body.partnership.tiers[0].hurdle?.conditions[0].kind).toBe('irr');
    expect(payload.investment_id).toBe('inv-1');
  });

  it('sends the explicit “no Partnership” as a literal null (P7.9 Stage 2)', async () => {
    const fetchMock = stubFetch(
      jsonResponse(200, { deal_id: 'deal-1', investment_id: null, partnership: null }),
    );
    await saveDealPartnership('deal-1', null);

    const [, init] = fetchMock.mock.calls[0];
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    // Present, and null: an omitted key would not be a statement at all.
    expect('partnership' in body).toBe(true);
    expect(body.partnership).toBeNull();
    expect(String(init?.body)).toBe('{"partnership":null}');
  });

  it('reads and saves a visible Investment’s Partnership on its own routes', async () => {
    const read = stubFetch(jsonResponse(200, { investment_id: 'inv-1', partnership: null }));
    await readInvestmentPartnership('inv-1');
    expect(read).toHaveBeenCalledWith(`${BASE}/investments/inv-1/partnership`, { method: 'GET' });

    vi.unstubAllGlobals();
    const save = stubFetch(
      jsonResponse(200, { investment_id: 'inv-1', partnership: PARTNERSHIP }),
    );
    await saveInvestmentPartnership('inv-1', PARTNERSHIP);
    const [url, init] = save.mock.calls[0];
    expect(url).toBe(`${BASE}/investments/inv-1/partnership`);
    expect(init?.method).toBe('PUT');
    expect(JSON.parse(String(init?.body))).toEqual({ partnership: PARTNERSHIP });
  });

  it('percent-encodes every id it puts in a path', async () => {
    const fetchMock = stubFetch(
      jsonResponse(200, { deal_id: 'a/b', investment_id: null, partnership: null }),
    );
    await readDealPartnership('a/b');
    expect(fetchMock.mock.calls[0][0]).toBe(`${BASE}/deals/a%2Fb/partnership`);
  });
});

describe('the Partnership variant routes', () => {
  it('reads the three layered fingerprints without executing anything', async () => {
    const fetchMock = stubFetch(
      jsonResponse(200, {
        investment_id: 'inv-1',
        strategy_id: 'base',
        scenario_id: 'base',
        root_kind: 'hidden_unit',
        unit_ids: ['deal-1'],
        partnership: PARTNERSHIP,
        partnership_source: 'base',
        project_source_fingerprint: 'p',
        structured_source_fingerprint: 's',
        partnership_source_fingerprint: 'w',
      }),
    );
    const payload = await readPartnershipVariantFingerprint('inv-1', 'base', 'base');

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE}/investments/inv-1/partnership-variants/base/base/fingerprint`,
      { method: 'GET' },
    );
    expect(payload.partnership_source_fingerprint).toBe('w');
    expect(payload.partnership_source).toBe('base');
  });

  it('carries a null Partnership fingerprint when the variant resolves none (FP-2)', async () => {
    stubFetch(
      jsonResponse(200, {
        investment_id: 'inv-1',
        strategy_id: 'strat-1',
        scenario_id: 'base',
        root_kind: 'hidden_unit',
        unit_ids: ['deal-1'],
        partnership: null,
        partnership_source: 'strategy',
        project_source_fingerprint: 'p',
        structured_source_fingerprint: 's',
        partnership_source_fingerprint: null,
      }),
    );
    const payload = await readPartnershipVariantFingerprint('inv-1', 'strat-1', 'base');
    expect(payload.partnership).toBeNull();
    expect(payload.partnership_source_fingerprint).toBeNull();
  });

  it('POSTs the analysis and returns exactly what the engine produced', async () => {
    const result = {
      status: 'complete',
      unavailable_reason: null,
      unavailable_message: null,
      upstream_reason: null,
      upstream_requirement_ids: [],
      cadence: 'annual',
      promote_participant_ids: ['gp'],
      common_equity_cash_flows: [-1000000, 120000],
      common_equity_total_profit: 480000,
      partners: [],
      tiers: [],
      periods: [],
    };
    const fetchMock = stubFetch(
      jsonResponse(200, {
        investment_id: 'inv-1',
        strategy_id: 'base',
        scenario_id: 'base',
        root_kind: 'hidden_unit',
        unit_ids: ['deal-1'],
        hold_period: 5,
        partnership: PARTNERSHIP,
        partnership_source: 'base',
        project_source_fingerprint: 'p',
        structured_source_fingerprint: 's',
        partnership_source_fingerprint: 'w',
        project_cache_status: 'hit',
        result,
      }),
    );
    const payload = await analyzePartnershipVariant('inv-1', 'base', 'base');

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE}/investments/inv-1/partnership-variants/base/base/analysis`,
      { method: 'POST' },
    );
    // Echoed, not recomputed: the client is a courier.
    expect(payload.result?.common_equity_total_profit).toBe(480000);
    expect(payload.result?.common_equity_cash_flows).toEqual([-1000000, 120000]);
  });

  it('treats an unavailable Common Equity Cash Flow as a successful analysis', async () => {
    stubFetch(
      jsonResponse(200, {
        investment_id: 'inv-1',
        strategy_id: 'base',
        scenario_id: 'base',
        root_kind: 'hidden_unit',
        unit_ids: ['deal-1'],
        hold_period: 5,
        partnership: PARTNERSHIP,
        partnership_source: 'base',
        project_source_fingerprint: 'p',
        structured_source_fingerprint: 's',
        partnership_source_fingerprint: 'w',
        project_cache_status: 'hit',
        result: {
          status: 'unavailable',
          unavailable_reason: 'common_equity_unavailable',
          unavailable_message: 'Funding Requirement req-1 is unresolved.',
          upstream_reason: 'unresolved_funding_requirement',
          upstream_requirement_ids: ['req-1'],
          cadence: 'annual',
          promote_participant_ids: ['gp'],
          common_equity_cash_flows: null,
          common_equity_total_profit: null,
          partners: null,
          tiers: null,
          periods: null,
        },
      }),
    );
    // No throw: an unavailable upstream is not an error (Section 13).
    const payload = await analyzePartnershipVariant('inv-1', 'base', 'base');
    expect(payload.result?.status).toBe('unavailable');
    expect(payload.result?.upstream_requirement_ids).toEqual(['req-1']);
    expect(payload.result?.partners).toBeNull();
  });
});

describe('the Partner perspective routes', () => {
  it('lists the addressable partners', async () => {
    const fetchMock = stubFetch(
      jsonResponse(200, {
        investment_id: 'inv-1',
        partners: [
          { partner_id: 'gp', name: 'Sponsor GP', present_in_base: true, strategy_ids: ['s1'] },
        ],
      }),
    );
    const payload = await listPartnerPerspectives('inv-1');
    expect(fetchMock).toHaveBeenCalledWith(`${BASE}/investments/inv-1/partner-perspectives`, {
      method: 'GET',
    });
    expect(payload.partners[0].partner_id).toBe('gp');
  });

  it('POSTs one partner’s Decision Matrix by its stable id', async () => {
    const fetchMock = stubFetch(
      jsonResponse(200, {
        investment_id: 'inv-1',
        root_kind: 'hidden_unit',
        unit_ids: ['deal-1'],
        partner: { partner_id: 'gp', name: 'Sponsor GP', present_in_base: true, strategy_ids: [] },
        matrix: { perspective: 'partner', partner_id: 'gp' },
      }),
    );
    const payload = await analyzePartnerDecisionMatrix('inv-1', 'gp');
    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE}/investments/inv-1/partner-decision-matrix/gp`,
      { method: 'POST' },
    );
    expect(payload.partner.partner_id).toBe('gp');
  });
});

describe('a refused Partnership keeps the backend’s own issues', () => {
  it('carries every Stage 1 validation issue, with its partner, tier and field', async () => {
    stubFetch(
      jsonResponse(422, {
        detail: [
          {
            code: 'shares_do_not_sum_to_one',
            message: 'Commitment shares must sum to 1.',
            partner_id: null,
            tier_id: null,
            field: 'commitment_share',
          },
          {
            code: 'missing_simple_distribution_order',
            message: 'A SIMPLE condition must state a distribution order.',
            partner_id: null,
            tier_id: 'tier-1',
            field: 'simple_distribution_order',
          },
        ],
      }),
    );

    await expect(saveDealPartnership('deal-1', PARTNERSHIP)).rejects.toBeInstanceOf(
      PartnershipError,
    );

    try {
      await saveDealPartnership('deal-1', PARTNERSHIP);
      expect.unreachable('the refusal should have thrown');
    } catch (error) {
      const refusal = error as PartnershipError;
      expect(refusal.issues).toHaveLength(2);
      expect(refusal.issues[1]).toEqual({
        code: 'missing_simple_distribution_order',
        message: 'A SIMPLE condition must state a distribution order.',
        partner_id: null,
        tier_id: 'tier-1',
        field: 'simple_distribution_order',
        // Absent on a validation issue, and reported as absent rather than
        // invented.
        period: null,
      });
      // The message is every issue, so nothing is lost when only it is shown.
      expect(refusal.message).toContain('Commitment shares must sum to 1.');
      expect(refusal.message).toContain('A SIMPLE condition must state a distribution order.');
    }
  });

  it('carries an execution issue’s tier and period, which a validation issue has not', async () => {
    stubFetch(
      jsonResponse(422, {
        detail: [
          {
            code: 'no_contributions_for_pro_rata_split',
            message: 'Tier tier-3 must divide cash pro rata with no contributions in period 1.',
            tier_id: 'tier-3',
            period: 1,
          },
        ],
      }),
    );
    try {
      await analyzePartnershipVariant('inv-1', 'base', 'base');
      expect.unreachable('the refusal should have thrown');
    } catch (error) {
      const refusal = error as PartnershipError;
      expect(refusal.issues[0]).toEqual({
        code: 'no_contributions_for_pro_rata_split',
        message: 'Tier tier-3 must divide cash pro rata with no contributions in period 1.',
        partner_id: null,
        tier_id: 'tier-3',
        field: null,
        period: 1,
      });
    }
  });

  it('reports a network failure as a Partnership refusal with no issues', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('network down');
      }),
    );
    try {
      await readDealPartnership('deal-1');
      expect.unreachable('the failure should have thrown');
    } catch (error) {
      expect(error).toBeInstanceOf(PartnershipError);
      expect((error as PartnershipError).issues).toEqual([]);
    }
  });
});
