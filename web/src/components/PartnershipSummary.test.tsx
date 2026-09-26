/**
 * Workstation polish pass -- the saved Partnership summary states the
 * partners and the waterfall in the analyst's own terms, in saved order, and
 * infers nothing.
 */

import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { Partnership } from '../partnershipTypes';
import { PartnershipSummary } from './PartnershipSummary';

afterEach(cleanup);

const PARTNERSHIP: Partnership = {
  partners: [
    { partner_id: 'lp', name: 'Harbor Capital LP', role: 'lp', investor_class: 'class_a', commitment_share: 0.9 },
    { partner_id: 'gp', name: 'Sponsor GP', role: 'gp', investor_class: null, commitment_share: 0.1 },
  ],
  contribution_rule: 'pro_rata_by_commitment',
  promote_benchmark: {
    shares: [
      { partner_id: 'lp', share: 0.8 },
      { partner_id: 'gp', share: 0.2 },
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
        hurdle_subject: { kind: 'partner', partner_id: 'lp', investor_class: null, account: null },
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
      name: 'GP Catch-Up',
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
      catch_up: { recipient: { kind: 'partner', partner_id: 'gp', investor_class: null }, target_profit_share: 0.2 },
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

describe('the saved Partnership summary', () => {
  it('states each partner’s commitment, benchmark share and promote participation as authored', () => {
    render(<PartnershipSummary partnership={PARTNERSHIP} />);
    const partners = screen.getByLabelText('Saved partners');
    expect(within(partners).getByText('Contributions: Pro Rata by Commitment')).toBeTruthy();
    const [lp, gp] = within(partners).getAllByRole('row').slice(1);
    expect(within(lp).getByText('90%')).toBeTruthy();
    expect(within(lp).getByText('80%')).toBeTruthy();
    expect(within(lp).getByText('No promote')).toBeTruthy();
    expect(within(gp).getByText('10%')).toBeTruthy();
    expect(within(gp).getByText('20%')).toBeTruthy();
    expect(within(gp).getByText('Promote participant')).toBeTruthy();
  });

  it('runs the waterfall in saved order, each tier marked with its own sequence', () => {
    render(<PartnershipSummary partnership={PARTNERSHIP} />);
    const tiers = within(screen.getByLabelText('Saved waterfall tiers')).getAllByRole('listitem');
    expect(tiers.map((tier) => tier.querySelector('.partnership-flow-name')?.textContent)).toEqual([
      'Preferred Return',
      'GP Catch-Up',
      'Residual',
    ]);
    expect(within(tiers[0]).getByLabelText('Sequence 1')).toBeTruthy();
    expect(within(tiers[2]).getByLabelText('Sequence 3')).toBeTruthy();
  });

  it('states each tier’s test, recipient and split in words', () => {
    render(<PartnershipSummary partnership={PARTNERSHIP} />);
    const [hurdle, catchUp, residual] = within(screen.getByLabelText('Saved waterfall tiers')).getAllByRole(
      'listitem',
    );
    expect(within(hurdle).getByText('Harbor Capital LP')).toBeTruthy();
    expect(within(hurdle).getByText('IRR Condition · 8.00% Simple · Accrued Return First')).toBeTruthy();
    expect(within(hurdle).getByText('Harbor Capital LP 100% · Sponsor GP 0%')).toBeTruthy();
    expect(within(catchUp).getByText('Sponsor GP')).toBeTruthy();
    expect(within(catchUp).getByText('20%')).toBeTruthy();
    expect(within(residual).getByText('Pro Rata by Contribution')).toBeTruthy();
  });
});
