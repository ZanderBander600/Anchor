/**
 * Phase 7 Gate P7.9 Stage 3 -- the Partnership form model.
 *
 * The one conversion between what the analyst types and the Stage 1 contract,
 * driven in both directions. What is proved here:
 *
 * - a saved Partnership survives a round trip **including every stable id**,
 *   because a Partner matrix and three fingerprints address partners and tiers
 *   by those ids (P-8);
 * - every required choice is genuinely unstated until the analyst states it, and
 *   the form refuses to build a request while one is;
 * - zero promote participants is a real answer that still needs confirming;
 * - the benchmark is built from its own column, never from the commitments;
 * - the unsupported catch-up combinations are never offered.
 *
 * The fixtures deliberately use a benchmark that differs from the commitment
 * shares. A form that quietly derived one from the other would produce a
 * different request and fail here (Q2, R-A).
 */

import { describe, expect, it } from 'vitest';
import {
  CATCH_UP_RECIPIENT_KIND_LABELS,
  EMPTY_PARTNERSHIP_FORM,
  formFromPartnership,
  newCondition,
  newPartner,
  newTier,
  nextConditionId,
  nextPartnerId,
  nextTierId,
  partnershipFromForm,
  splitRulesFor,
  unstatedPartnershipChoices,
  withCommitmentsCopiedToBenchmark,
  withSplitSharesForPartners,
  withTierKind,
} from './partnershipForm';
import type { PartnershipForm, TierForm } from './partnershipForm';
import type { Partnership } from './partnershipTypes';

/** A whole partnership whose benchmark is deliberately **not** its commitments:
 * 90/10 committed, 80/20 benchmarked. */
const SAVED: Partnership = {
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
          { kind: 'moic', condition_id: 'cond-2', multiple: 1.5 },
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

describe('a saved Partnership survives the round trip', () => {
  it('rebuilds the contract exactly, every stable id kept (P-8)', () => {
    expect(partnershipFromForm(formFromPartnership(SAVED))).toEqual(SAVED);
  });

  it('keeps the partner, tier and condition ids the matrix addresses', () => {
    const form = formFromPartnership(SAVED);
    expect(form.partners.map((partner) => partner.partnerId)).toEqual(['lp', 'gp']);
    expect(form.tiers.map((tier) => tier.tierId)).toEqual(['tier-1', 'tier-2', 'tier-3']);
    expect(form.tiers[0].conditions.map((condition) => condition.conditionId)).toEqual([
      'cond-1',
      'cond-2',
    ]);
    // Renaming a partner does not move its identity.
    const renamed: PartnershipForm = {
      ...form,
      partners: form.partners.map((partner) =>
        partner.partnerId === 'lp' ? { ...partner, name: 'A different name' } : partner,
      ),
    };
    const rebuilt = partnershipFromForm(renamed);
    expect(rebuilt.partners[0].partner_id).toBe('lp');
    expect(rebuilt.partners[0].name).toBe('A different name');
  });

  it('reads the benchmark from its own table, not from the commitments (Q2)', () => {
    const form = formFromPartnership(SAVED);
    expect(form.partners.map((partner) => partner.commitmentShare)).toEqual(['90', '10']);
    expect(form.partners.map((partner) => partner.benchmarkShare)).toEqual(['80', '20']);
    const rebuilt = partnershipFromForm(form);
    expect(rebuilt.promote_benchmark.shares).toEqual([
      { partner_id: 'lp', share: 0.8 },
      { partner_id: 'gp', share: 0.2 },
    ]);
  });

  it('round-trips a reopened Partnership as already confirmed', () => {
    // It has been through the validator, so its participant set is stated.
    expect(formFromPartnership(SAVED).promoteParticipantsConfirmed).toBe(true);
  });

  it('carries every typed union member through, with its display scale', () => {
    const form = formFromPartnership(SAVED);
    const [hurdle, catchUp, residual] = form.tiers;
    expect(hurdle.splitRule).toBe('explicit');
    expect(hurdle.subjectKind).toBe('partner');
    expect(hurdle.subjectPartnerId).toBe('lp');
    expect(hurdle.combinator).toBe('all');
    expect(hurdle.conditions[0]).toMatchObject({
      kind: 'irr',
      rate: '8',
      accrualConvention: 'simple',
      simpleDistributionOrder: 'accrued_return_first',
    });
    expect(hurdle.conditions[1]).toMatchObject({ kind: 'moic', multiple: '1.5' });
    expect(catchUp.recipientKind).toBe('partner');
    expect(catchUp.recipientPartnerId).toBe('gp');
    expect(catchUp.targetProfitShare).toBe('20');
    expect(residual.splitRule).toBe('pro_rata_by_contribution');
  });

  it('states a SIMPLE order only on a SIMPLE condition', () => {
    const form = formFromPartnership(SAVED);
    const compounding: PartnershipForm = {
      ...form,
      tiers: form.tiers.map((tier) =>
        tier.tierId === 'tier-1'
          ? {
              ...tier,
              conditions: tier.conditions.map((condition) =>
                condition.conditionId === 'cond-1'
                  ? { ...condition, accrualConvention: 'annual_compound' as const }
                  : condition,
              ),
            }
          : tier,
      ),
    };
    const rebuilt = partnershipFromForm(compounding);
    const condition = rebuilt.tiers[0].hurdle?.conditions[0];
    expect(condition).toMatchObject({ kind: 'irr', accrual_convention: 'annual_compound' });
    // Forbidden on anything but SIMPLE, so it is dropped rather than carried.
    expect(condition && 'simple_distribution_order' in condition && condition.simple_distribution_order).toBeNull();
  });
});

describe('nothing economic is defaulted', () => {
  it('starts a new Partnership with every choice unstated', () => {
    expect(EMPTY_PARTNERSHIP_FORM).toEqual({
      partners: [],
      contributionRule: '',
      promoteParticipantIds: [],
      promoteParticipantsConfirmed: false,
      tiers: [],
    });
  });

  it('starts a new partner, tier and condition with nothing assumed', () => {
    const partner = newPartner(EMPTY_PARTNERSHIP_FORM);
    expect(partner).toMatchObject({ role: '', commitmentShare: '', benchmarkShare: '' });

    const tier = newTier(EMPTY_PARTNERSHIP_FORM, 'hurdle');
    expect(tier).toMatchObject({
      splitRule: '',
      subjectKind: '',
      combinator: '',
      recipientKind: '',
      targetProfitShare: '',
      sequence: '',
    });

    expect(newCondition(tier)).toMatchObject({
      kind: '',
      rate: '',
      accrualConvention: '',
      simpleDistributionOrder: '',
      multiple: '',
    });
  });

  it('reports every unstated choice, located at what it belongs to', () => {
    const partner = newPartner(EMPTY_PARTNERSHIP_FORM);
    const withPartner: PartnershipForm = { ...EMPTY_PARTNERSHIP_FORM, partners: [partner] };
    const hurdle = newTier(withPartner, 'hurdle');
    const condition = newCondition(hurdle);
    const form: PartnershipForm = {
      ...withPartner,
      tiers: [{ ...hurdle, conditions: [condition] }],
    };

    const choices = unstatedPartnershipChoices(form).map((choice) => choice.choice);
    expect(choices).toContain('contribution_rule');
    expect(choices).toContain('promote_participants');
    expect(choices).toContain('partner_role');
    expect(choices).toContain('benchmark_share');
    expect(choices).toContain('split_rule');
    expect(choices).toContain('hurdle_subject');
    expect(choices).toContain('combinator');
    expect(choices).toContain('condition_kind');

    // Each is located, because two tiers may share a display name.
    const splitRule = unstatedPartnershipChoices(form).find(
      (choice) => choice.choice === 'split_rule',
    );
    expect(splitRule?.tierId).toBe(hurdle.tierId);
    const role = unstatedPartnershipChoices(form).find(
      (choice) => choice.choice === 'partner_role',
    );
    expect(role?.partnerId).toBe(partner.partnerId);
  });

  it('asks for a SIMPLE distribution order only once SIMPLE is chosen', () => {
    const base = formFromPartnership(SAVED);
    const blankOrder: PartnershipForm = {
      ...base,
      tiers: base.tiers.map((tier) =>
        tier.tierId === 'tier-1'
          ? {
              ...tier,
              conditions: tier.conditions.map((condition) =>
                condition.conditionId === 'cond-1'
                  ? { ...condition, simpleDistributionOrder: '' as const }
                  : condition,
              ),
            }
          : tier,
      ),
    };
    expect(
      unstatedPartnershipChoices(blankOrder).map((choice) => choice.choice),
    ).toContain('simple_distribution_order');

    // The same condition under `annual_compound` must not ask for one at all.
    const compounding: PartnershipForm = {
      ...blankOrder,
      tiers: blankOrder.tiers.map((tier) =>
        tier.tierId === 'tier-1'
          ? {
              ...tier,
              conditions: tier.conditions.map((condition) =>
                condition.conditionId === 'cond-1'
                  ? { ...condition, accrualConvention: 'annual_compound' as const }
                  : condition,
              ),
            }
          : tier,
      ),
    };
    expect(
      unstatedPartnershipChoices(compounding).map((choice) => choice.choice),
    ).not.toContain('simple_distribution_order');
  });

  it('refuses to build a request while a choice is unstated, naming it', () => {
    expect(() => partnershipFromForm(EMPTY_PARTNERSHIP_FORM)).toThrow(/contribution rule/i);

    const base = formFromPartnership(SAVED);
    const noRole: PartnershipForm = {
      ...base,
      partners: base.partners.map((partner) =>
        partner.partnerId === 'lp' ? { ...partner, role: '' as const } : partner,
      ),
    };
    expect(() => partnershipFromForm(noRole)).toThrow(/Harbor Capital LP: select a role/);

    const noSubject: PartnershipForm = {
      ...base,
      tiers: base.tiers.map((tier) =>
        tier.tierId === 'tier-1' ? { ...tier, subjectKind: '' as const } : tier,
      ),
    };
    expect(() => partnershipFromForm(noSubject)).toThrow(/whose return the hurdle measures/);

    const noRecipient: PartnershipForm = {
      ...base,
      tiers: base.tiers.map((tier) =>
        tier.tierId === 'tier-2' ? { ...tier, recipientKind: '' as const } : tier,
      ),
    };
    expect(() => partnershipFromForm(noRecipient)).toThrow(/who receives the catch-up/);

    const blankBenchmark: PartnershipForm = {
      ...base,
      partners: base.partners.map((partner) =>
        partner.partnerId === 'gp' ? { ...partner, benchmarkShare: '' } : partner,
      ),
    };
    expect(() => partnershipFromForm(blankBenchmark)).toThrow(/benchmark share is required/i);
  });

  it('sends an unstated split rule as null, for the validator to refuse by name', () => {
    const base = formFromPartnership(SAVED);
    const noSplit: PartnershipForm = {
      ...base,
      tiers: base.tiers.map((tier) =>
        tier.tierId === 'tier-3' ? { ...tier, splitRule: '' as const } : tier,
      ),
    };
    // `missing_split` is the backend's refusal; the form does not invent one.
    expect(partnershipFromForm(noSplit).tiers[2].split).toBeNull();
  });
});

describe('promote participants are confirmed explicitly, including none (Q10)', () => {
  it('refuses an unconfirmed set even when it is empty', () => {
    const base = formFromPartnership(SAVED);
    const unconfirmed: PartnershipForm = {
      ...base,
      promoteParticipantIds: [],
      promoteParticipantsConfirmed: false,
    };
    expect(() => partnershipFromForm(unconfirmed)).toThrow(/Confirm which partners earn a promote/);
    expect(
      unstatedPartnershipChoices(unconfirmed).map((choice) => choice.choice),
    ).toContain('promote_participants');
  });

  it('accepts a confirmed empty set as the stated answer, not an omission', () => {
    const base = formFromPartnership(SAVED);
    const none: PartnershipForm = {
      ...base,
      promoteParticipantIds: [],
      promoteParticipantsConfirmed: true,
    };
    expect(partnershipFromForm(none).promote_participant_ids).toEqual([]);
    expect(
      unstatedPartnershipChoices(none).map((choice) => choice.choice),
    ).not.toContain('promote_participants');
  });

  it('infers no participant from a GP role', () => {
    const base = formFromPartnership(SAVED);
    const none: PartnershipForm = {
      ...base,
      promoteParticipantIds: [],
      promoteParticipantsConfirmed: true,
    };
    const rebuilt = partnershipFromForm(none);
    // The GP is still a GP, and still earns no promote: the role selects
    // nothing (Section 4.2).
    expect(rebuilt.partners[1].role).toBe('gp');
    expect(rebuilt.promote_participant_ids).toEqual([]);
  });
});

describe('the unsupported combinations are never offered (Section 18)', () => {
  it('offers no economic-account catch-up recipient', () => {
    expect(Object.keys(CATCH_UP_RECIPIENT_KIND_LABELS)).toEqual(['partner', 'investor_class']);
  });

  it('offers no pro-rata split on a catch-up tier (R-D)', () => {
    expect(splitRulesFor('catch_up')).toEqual(['explicit']);
    expect(splitRulesFor('hurdle')).toEqual(['explicit', 'pro_rata_by_contribution']);
    expect(splitRulesFor('residual')).toEqual(['explicit', 'pro_rata_by_contribution']);
  });

  it('drops a split rule the new tier kind does not permit', () => {
    const proRata: TierForm = {
      ...newTier(EMPTY_PARTNERSHIP_FORM, 'residual'),
      splitRule: 'pro_rata_by_contribution',
    };
    // Becoming a catch-up cannot silently keep an invalid split rule.
    expect(withTierKind(proRata, 'catch_up').splitRule).toBe('');
    // Becoming a hurdle may keep it: it is permitted there.
    expect(withTierKind(proRata, 'hurdle').splitRule).toBe('pro_rata_by_contribution');
  });
});

describe('editing the partner set keeps the tables coherent', () => {
  it('copies commitments into the benchmark as values, never as a link', () => {
    const base = formFromPartnership(SAVED);
    const copied = withCommitmentsCopiedToBenchmark(base);
    expect(copied.partners.map((partner) => partner.benchmarkShare)).toEqual(['90', '10']);

    // Changing a commitment afterwards does not follow into the benchmark.
    const moved: PartnershipForm = {
      ...copied,
      partners: copied.partners.map((partner) =>
        partner.partnerId === 'lp' ? { ...partner, commitmentShare: '70' } : partner,
      ),
    };
    expect(moved.partners[0].benchmarkShare).toBe('90');
  });

  it('gives a new partner a blank share and drops a removed one', () => {
    const base = formFromPartnership(SAVED);
    const tier = base.tiers[0];
    const withNew = withSplitSharesForPartners(tier, ['lp', 'gp', 'newcomer']);
    expect(withNew.splitShares).toEqual({ lp: '100', gp: '0', newcomer: '' });

    const withoutLp = withSplitSharesForPartners(tier, ['gp']);
    expect(withoutLp.splitShares).toEqual({ gp: '0' });
  });

  it('mints readable, stable ids that never collide', () => {
    expect(nextPartnerId(EMPTY_PARTNERSHIP_FORM)).toBe('partner-1');
    const form = formFromPartnership(SAVED);
    expect(nextTierId(form)).toBe('tier-4');
    expect(nextConditionId(form.tiers[0])).toBe('tier-1-condition-1');

    const one: PartnershipForm = {
      ...EMPTY_PARTNERSHIP_FORM,
      partners: [newPartner(EMPTY_PARTNERSHIP_FORM)],
    };
    expect(nextPartnerId(one)).toBe('partner-2');
  });
});
