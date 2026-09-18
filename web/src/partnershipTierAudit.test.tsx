/**
 * P7.9 closeout -- the Tier Audit reads each figure by its own period, and
 * names each hurdle condition in words.
 *
 * **The period defect.** A `TierResult` carries two per-period series with
 * different shapes. `amounts` is dense: the engine allocates one entry per
 * period of the Common Equity Cash Flow, index 0 being closing, and writes
 * `amounts[period]` (`partnership/waterfall.py`; the backend conservation test
 * reads `tier.amounts[t]` the same way). `shares_by_period` is sparse: the
 * engine appends an entry, carrying its own `period`, only for a period in
 * which the tier paid. Reading `amounts[index]` beside the index-th sparse row
 * therefore printed another period's cash -- on the P7.9 QA Deal, a Preferred
 * Return of $0 in Year 1 and a Catch-Up and Residual of $0 in Year 5.
 *
 * The fixture below is the live engine's result for that deal, figure for
 * figure: a zero at period 0, shares beginning at period 1, and two tiers that
 * pay only in period 5. It is chosen so that, in every row, the value at the
 * row's position differs from the value at the row's period -- so a surface
 * that indexed by position cannot pass (the proof is asserted, not assumed).
 *
 * **Condition identity.** A `condition_id` is opaque. It keys rows and elements
 * and is never shown; the label comes from the saved Partnership contract.
 */

import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import { PartnershipResults } from './components/PartnershipResults';
import { conditionAuditLabels } from './partnershipForm';
import { formatCurrency } from './format';
import type {
  HurdleAccountRecord,
  HurdleCondition,
  Partnership,
  PartnerResult,
  PartnershipResult,
  TierResult,
} from './partnershipTypes';

afterEach(cleanup);

// =============================================================================
// The live engine's shape (P7.9 QA Deal, Base Strategy x Base Scenario)
// =============================================================================

const PERIODS = [0, 1, 2, 3, 4, 5];

const PREF_AMOUNTS = [0, 1720000, 1825000, 1640249.603882798, 1751644.103882798, 17896458.11];
const CATCH_UP_AMOUNTS = [0, 0, 0, 0, 0, 3812087.9];
const RESIDUAL_AMOUNTS = [0, 0, 0, 0, 0, 18070737.05];

const LP_GP = [
  { partner_id: 'partner-1', share: 0.9 },
  { partner_id: 'partner-2', share: 0.1 },
];

const IRR_CONDITION: HurdleCondition = {
  kind: 'irr',
  condition_id: 'tier-1-condition-1',
  rate: 0.08,
  accrual_convention: 'annual_compound',
  simple_distribution_order: null,
};

const MOIC_CONDITION: HurdleCondition = {
  kind: 'moic',
  condition_id: 'tier-1-condition-2',
  multiple: 1.5,
};

function partnershipWith(conditions: HurdleCondition[]): Partnership {
  return {
    partners: [
      { partner_id: 'partner-1', name: 'Harbor Capital LP', role: 'lp', investor_class: 'class_a', commitment_share: 0.9 },
      { partner_id: 'partner-2', name: 'Sponsor GP', role: 'gp', investor_class: null, commitment_share: 0.1 },
    ],
    contribution_rule: 'pro_rata_by_commitment',
    promote_benchmark: { shares: LP_GP },
    promote_participant_ids: ['partner-2'],
    tiers: [
      {
        tier_id: 'tier-1',
        name: 'Preferred Return',
        sequence: 1,
        kind: 'hurdle',
        split: { kind: 'explicit', shares: LP_GP },
        hurdle: {
          hurdle_subject: { kind: 'partner', partner_id: 'partner-1', investor_class: null, account: null },
          conditions,
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
            { partner_id: 'partner-1', share: 0.4 },
            { partner_id: 'partner-2', share: 0.6 },
          ],
        },
        hurdle: null,
        catch_up: {
          recipient: { kind: 'partner', partner_id: 'partner-2', investor_class: null },
          target_profit_share: 0.2,
        },
      },
      {
        tier_id: 'tier-3',
        name: 'Residual',
        sequence: 3,
        kind: 'residual',
        split: {
          kind: 'explicit',
          shares: [
            { partner_id: 'partner-1', share: 0.7 },
            { partner_id: 'partner-2', share: 0.3 },
          ],
        },
        hurdle: null,
        catch_up: null,
      },
    ],
  };
}

function accountRecords(conditionId: string): HurdleAccountRecord[] {
  return PERIODS.map((period) => ({
    condition_id: conditionId,
    period,
    opening_balance: 1000,
    accrual: 10,
    subject_contributions: 0,
    subject_distributions_before_tier: 0,
    subject_distributions_from_tier: 0,
    subject_distributions_after_tier: 0,
    closing_balance: 1010,
    capacity_at_entry: null,
    satisfied_at_close: false,
    simple_distribution_order: null,
    outstanding_capital: null,
    accrued_return: null,
  }));
}

function tier(
  overrides: Partial<TierResult> & Pick<TierResult, 'tier_id' | 'sequence' | 'kind' | 'amounts'>,
): TierResult {
  return {
    split_rule: 'explicit',
    shares_by_period: [],
    hurdle_subject: null,
    subject_partner_ids: null,
    combinator: null,
    catch_up_recipient: null,
    recipient_partner_ids: null,
    catch_up_rate: null,
    target_profit_share: null,
    partner_amounts: [],
    conditions: [],
    catch_up_records: [],
    ...overrides,
  };
}

function partnerResult(partnerId: string): PartnerResult {
  return {
    partner_id: partnerId,
    role: 'lp',
    investor_class: null,
    commitment_share: 0.9,
    benchmark_share: 0.9,
    benchmark_equals_commitment: true,
    is_promote_participant: false,
    contributions: [],
    distributions: [],
    net_cash_flows: [],
    total_contributions: 1,
    total_distributions: 2,
    profit: 1,
    irr: 0.1,
    irr_status: 'defined',
    moic: 2,
    moic_unavailable_reason: null,
    benchmark_distributions: [],
    total_benchmark_distributions: 2,
    capital_returned: 1,
    profit_distributions: 1,
    benchmark_capital_returned: 1,
    benchmark_profit_distributions: 1,
    distribution_difference: 0,
    distribution_advantage: 0,
    distribution_disadvantage: 0,
    capital_return_difference: 0,
    profit_distribution_difference: 0,
    promote_earned: null,
    promote_unavailable_reason: 'not_a_promote_participant',
    benchmark_capital_subordination: 0,
    distributions_by_tier: [],
    capital_return_difference_by_tier: [],
    profit_distribution_difference_by_tier: [],
    promote_attribution_by_tier: null,
  };
}

function resultWith(conditionIds: string[]): PartnershipResult {
  return {
    status: 'complete',
    unavailable_reason: null,
    unavailable_message: null,
    upstream_reason: null,
    upstream_requirement_ids: [],
    cadence: 'annual',
    promote_participant_ids: ['partner-2'],
    common_equity_cash_flows: [-19170000, 1720000, 1825000, 1640249.6, 1751644.1, 39779283.06],
    common_equity_total_profit: 1,
    partners: [partnerResult('partner-1')],
    tiers: [
      tier({
        tier_id: 'tier-1',
        sequence: 1,
        kind: 'hurdle',
        hurdle_subject: { kind: 'partner', partner_id: 'partner-1', investor_class: null, account: null },
        subject_partner_ids: ['partner-1'],
        combinator: 'all',
        // Sparse: the tier first pays in period 1, never at closing.
        shares_by_period: [1, 2, 3, 4, 5].map((period) => ({
          period,
          shares: [
            { partner_id: 'partner-1', share: 0.9 },
            { partner_id: 'partner-2', share: 0.1 },
          ],
        })),
        amounts: PREF_AMOUNTS,
        conditions: conditionIds.flatMap(accountRecords),
      }),
      tier({
        tier_id: 'tier-2',
        sequence: 2,
        kind: 'catch_up',
        catch_up_recipient: { kind: 'partner', partner_id: 'partner-2', investor_class: null },
        recipient_partner_ids: ['partner-2'],
        catch_up_rate: 0.6,
        target_profit_share: 0.2,
        // Sparse: only period 5.
        shares_by_period: [
          {
            period: 5,
            shares: [
              { partner_id: 'partner-1', share: 0.4 },
              { partner_id: 'partner-2', share: 0.6 },
            ],
          },
        ],
        amounts: CATCH_UP_AMOUNTS,
      }),
      tier({
        tier_id: 'tier-3',
        sequence: 3,
        kind: 'residual',
        shares_by_period: [
          {
            period: 5,
            shares: [
              { partner_id: 'partner-1', share: 0.7 },
              { partner_id: 'partner-2', share: 0.3 },
            ],
          },
        ],
        amounts: RESIDUAL_AMOUNTS,
      }),
    ],
    periods: null,
  };
}

const PARTNER_NAMES = { 'partner-1': 'Harbor Capital LP', 'partner-2': 'Sponsor GP' };
const TIER_NAMES = { 'tier-1': 'Preferred Return', 'tier-2': 'Catch-Up', 'tier-3': 'Residual' };

function renderAudit(partnership: Partnership, result: PartnershipResult) {
  return render(
    <PartnershipResults
      result={result}
      partnerNames={PARTNER_NAMES}
      tierNames={TIER_NAMES}
      conditionLabels={conditionAuditLabels(partnership)}
    />,
  );
}

function tierArticle(container: HTMLElement, tierId: string): HTMLElement {
  return container.querySelector(`article.partnership-tier[data-tier="${tierId}"]`) as HTMLElement;
}

/** The Tier Distribution shown in one tier's period row. */
function shownAmount(article: HTMLElement, period: number): string {
  const cell = article.querySelector(`tr[data-period="${period}"] > [data-field="tier_amount"]`);
  return (cell as HTMLElement).textContent ?? '';
}

// =============================================================================
// 1. Each period's amount is that period's
// =============================================================================

describe('the Tier Audit reads each tier amount by its own period', () => {
  const partnership = partnershipWith([IRR_CONDITION]);
  const result = resultWith([IRR_CONDITION.condition_id]);

  it('shows the backend amount for every visible period of every tier', () => {
    const { container } = renderAudit(partnership, result);
    const expected: Record<string, Record<number, string>> = {
      'tier-1': {
        1: '$1,720,000',
        2: '$1,825,000',
        3: '$1,640,250',
        4: '$1,751,644',
        5: '$17,896,458',
      },
      'tier-2': { 5: '$3,812,088' },
      'tier-3': { 5: '$18,070,737' },
    };
    for (const [tierId, byPeriod] of Object.entries(expected)) {
      const article = tierArticle(container, tierId);
      const periods = [...article.querySelectorAll('tbody tr[data-period]')]
        .filter((row) => row.querySelector('[data-field="tier_amount"]') !== null)
        .map((row) => row.getAttribute('data-period'));
      expect(periods).toEqual(Object.keys(byPeriod));
      for (const [period, text] of Object.entries(byPeriod)) {
        expect(shownAmount(article, Number(period))).toBe(text);
      }
    }
  });

  it('labels the rows by the backend period: Year 1 first, and no Closing row', () => {
    const { container } = renderAudit(partnership, result);
    const pref = tierArticle(container, 'tier-1');
    const table = pref.querySelector('table') as HTMLElement;
    const headers = within(table)
      .getAllByRole('rowheader')
      .map((cell) => cell.textContent);
    expect(headers).toEqual(['Year 1', 'Year 2', 'Year 3', 'Year 4', 'Year 5']);
    expect(within(tierArticle(container, 'tier-2')).getAllByText('Year 5').length).toBeGreaterThan(0);
  });

  it('discriminates: indexing amounts by row position would print other figures', () => {
    // The proof that this fixture would catch the old `amounts[index]` read:
    // in every sparse row, the value at the row's position is not the value at
    // its period, and the surface shows the period's value, not the position's.
    const { container } = renderAudit(partnership, result);
    for (const tierResult of result.tiers ?? []) {
      const article = tierArticle(container, tierResult.tier_id);
      tierResult.shares_by_period.forEach((row, index) => {
        const byPeriod = formatCurrency(tierResult.amounts[row.period]);
        const byPosition = formatCurrency(tierResult.amounts[index]);
        expect(byPosition).not.toBe(byPeriod);
        expect(shownAmount(article, row.period)).toBe(byPeriod);
        expect(shownAmount(article, row.period)).not.toBe(byPosition);
      });
    }
    // The three figures the live defect printed are nowhere in these rows.
    const pref = tierArticle(container, 'tier-1');
    expect(shownAmount(pref, 1)).not.toBe('$0');
    expect(shownAmount(pref, 5)).not.toBe('$1,751,644');
    expect(shownAmount(tierArticle(container, 'tier-2'), 5)).not.toBe('$0');
    expect(shownAmount(tierArticle(container, 'tier-3'), 5)).not.toBe('$0');
  });
});

// =============================================================================
// 2. Conditions are named in words, identified by id
// =============================================================================

describe('the Tier Audit names hurdle conditions, never by their opaque id', () => {
  it('labels an IRR and a MOIC condition by kind and stated terms', () => {
    const partnership = partnershipWith([IRR_CONDITION, MOIC_CONDITION]);
    renderAudit(partnership, resultWith([IRR_CONDITION.condition_id, MOIC_CONDITION.condition_id]));
    expect(
      screen.getByRole('heading', {
        name: 'Hurdle Account: IRR Condition · 8.00% Annual Compound',
      }),
    ).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Hurdle Account: MOIC Condition · 1.50x' })).toBeTruthy();
  });

  it('renders no raw condition id anywhere in the visible text', () => {
    const partnership = partnershipWith([IRR_CONDITION, MOIC_CONDITION]);
    const { container } = renderAudit(
      partnership,
      resultWith([IRR_CONDITION.condition_id, MOIC_CONDITION.condition_id]),
    );
    expect(container.textContent).not.toContain('tier-1-condition-1');
    expect(container.textContent).not.toContain('tier-1-condition-2');
    expect(container.textContent).not.toMatch(/condition-\d/);
  });

  it('keeps the ids as element identity for each account and each row', () => {
    const partnership = partnershipWith([IRR_CONDITION, MOIC_CONDITION]);
    const { container } = renderAudit(
      partnership,
      resultWith([IRR_CONDITION.condition_id, MOIC_CONDITION.condition_id]),
    );
    const groups = [...container.querySelectorAll('.partnership-audit-condition[data-condition]')];
    expect(groups.map((group) => group.getAttribute('data-condition'))).toEqual([
      'tier-1-condition-1',
      'tier-1-condition-2',
    ]);
    // Each account holds exactly its own condition's six period rows.
    for (const group of groups) {
      const id = group.getAttribute('data-condition');
      const rows = [...group.querySelectorAll('tbody tr')];
      expect(rows).toHaveLength(6);
      expect(rows.every((row) => row.getAttribute('data-condition') === id)).toBe(true);
    }
  });

  it('keeps two IRR conditions distinguishable by their terms', () => {
    const higher: HurdleCondition = {
      kind: 'irr',
      condition_id: 'tier-1-condition-2',
      rate: 0.12,
      accrual_convention: 'simple',
      simple_distribution_order: 'capital_first',
    };
    const labels = conditionAuditLabels(partnershipWith([IRR_CONDITION, higher]))['tier-1'];
    expect(labels).toEqual({
      'tier-1-condition-1': 'IRR Condition · 8.00% Annual Compound',
      'tier-1-condition-2': 'IRR Condition · 12.00% Simple',
    });
    renderAudit(
      partnershipWith([IRR_CONDITION, higher]),
      resultWith([IRR_CONDITION.condition_id, higher.condition_id]),
    );
    expect(
      screen.getByRole('heading', { name: 'Hurdle Account: IRR Condition · 8.00% Annual Compound' }),
    ).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Hurdle Account: IRR Condition · 12.00% Simple' })).toBeTruthy();
  });

  it('still tells apart two conditions that state identical terms', () => {
    const twin: HurdleCondition = { ...IRR_CONDITION, condition_id: 'tier-1-condition-2' };
    const labels = conditionAuditLabels(partnershipWith([IRR_CONDITION, twin]))['tier-1'];
    expect(labels['tier-1-condition-1']).toBe('IRR Condition · 8.00% Annual Compound (1 of 2)');
    expect(labels['tier-1-condition-2']).toBe('IRR Condition · 8.00% Annual Compound (2 of 2)');
    expect(new Set(Object.values(labels)).size).toBe(2);
  });

  it('falls back to a plain word, never the id, for a condition the contract does not name', () => {
    const { container } = render(
      <PartnershipResults
        result={resultWith([IRR_CONDITION.condition_id])}
        partnerNames={PARTNER_NAMES}
        tierNames={TIER_NAMES}
        conditionLabels={{}}
      />,
    );
    expect(screen.getByRole('heading', { name: 'Hurdle Account: Condition' })).toBeTruthy();
    expect(container.textContent).not.toContain('tier-1-condition-1');
  });

  it('resolves labels from the saved contract, not from the id’s spelling', () => {
    // The same id, a different stated kind: the label follows the contract.
    const relabelled: HurdleCondition = {
      kind: 'moic',
      condition_id: IRR_CONDITION.condition_id,
      multiple: 2,
    };
    renderAudit(partnershipWith([relabelled]), resultWith([IRR_CONDITION.condition_id]));
    expect(screen.getByRole('heading', { name: 'Hurdle Account: MOIC Condition · 2.00x' })).toBeTruthy();
    expect(screen.queryByText(/IRR Condition/)).toBeNull();
  });
});
