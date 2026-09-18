/**
 * Phase 7 Gate P7.9 Stage 3 -- the Partnership editor's form model.
 *
 * The analyst edits strings; the backend receives the Stage 1 contract. This
 * module is the one conversion between them, in both directions, exactly as
 * `capitalStructureForm.ts` is for a Capital Structure -- and it reuses
 * `convert.ts`'s own parsers, so "what a percentage means on screen" is answered
 * once in this product.
 *
 * **No financial arithmetic.** The only numbers touched here are display scale:
 * a share typed as `90` and sent as `0.9`, a rate typed as `8` and sent as
 * `0.08`, the same conversion every assumption field already makes. Nothing is
 * summed, allocated, accrued, benchmarked or attributed; every contribution,
 * distribution, return, Promote Earned and subordination figure comes from the
 * Stage 1 engine.
 *
 * **No default is invented** (Section 17.3). Each of these is blank until the
 * analyst states it, and the form refuses to build a request while one is:
 * the contribution rule, a tier's split rule, a hurdle's subject, its
 * combinator, a condition's kind, an IRR condition's accrual convention, a
 * SIMPLE condition's distribution order, and a catch-up's recipient. The
 * benchmark is a literal table that starts empty -- it is **never** derived from
 * or linked to the commitment shares (Q2), though the editor may offer to copy
 * them in as literal values -- and the promote participants are an explicit
 * confirmation the analyst must make **even when the answer is none** (Q10).
 *
 * **Invalid combinations are not offered.** A catch-up recipient is never an
 * economic account, and a catch-up tier never takes a pro-rata split; both are
 * unsupported by design rather than deferred (Section 18), so the option lists
 * below simply do not contain them.
 *
 * **Identity is the id (P-8).** A partner's `partner_id` and a tier's `tier_id`
 * are stable and opaque: editing a name, a role, a share or a rate keeps them,
 * because a Strategy comparison and a Partner matrix address a partner by id.
 * New ids are minted only for genuinely new partners, tiers and conditions.
 */

import { formatDisplayNumber, parseNumber, parsePercent, parseWholeNumber } from './convert';
import type {
  CatchUpRecipientKind,
  ContributionRule,
  EconomicAccount,
  HurdleCombinator,
  HurdleCondition,
  HurdleSubjectKind,
  Partner,
  PartnerRole,
  PartnerShareRow,
  Partnership,
  PartnershipAccrualConvention,
  SimpleDistributionOrder,
  SplitRule,
  TierKind,
  TierSplit,
  WaterfallTier,
} from './partnershipTypes';

/** Which condition a hurdle states. Mirrors the codec's `HurdleConditionKind`;
 * `''` is the unstated choice. */
export type ConditionKind = 'irr' | 'moic';

// =============================================================================
// The option lists the editor offers
// =============================================================================

export const PARTNER_ROLE_LABELS: Readonly<Record<PartnerRole, string>> = {
  lp: 'LP',
  gp: 'GP',
  co_investor: 'Co-Investor',
};

export const CONTRIBUTION_RULE_LABELS: Readonly<Record<ContributionRule, string>> = {
  pro_rata_by_commitment: 'Pro Rata by Commitment',
};

export const TIER_KIND_LABELS: Readonly<Record<TierKind, string>> = {
  hurdle: 'Hurdle',
  catch_up: 'Catch-Up',
  residual: 'Residual',
};

export const SPLIT_RULE_LABELS: Readonly<Record<SplitRule, string>> = {
  explicit: 'Explicit Shares',
  pro_rata_by_contribution: 'Pro Rata by Contribution',
};

export const HURDLE_SUBJECT_KIND_LABELS: Readonly<Record<HurdleSubjectKind, string>> = {
  partner: 'One Partner',
  investor_class: 'An Investor Class',
  economic_account: 'All Common Equity',
};

export const ECONOMIC_ACCOUNT_LABELS: Readonly<Record<EconomicAccount, string>> = {
  all_common_equity: 'All Common Equity',
};

export const COMBINATOR_LABELS: Readonly<Record<HurdleCombinator, string>> = {
  all: 'All conditions must be met',
  any: 'Any condition may be met',
};

export const CONDITION_KIND_LABELS: Readonly<Record<ConditionKind, string>> = {
  irr: 'IRR',
  moic: 'MOIC',
};

/** What one condition is called on screen.
 *
 * A `condition_id` is a stable, opaque identity: it keys React, names the
 * element ids and travels in the contract, and it is deliberately **not** shown
 * to the analyst, who never authored it and cannot act on it. An unstated
 * condition is simply "Condition" until its kind says more; nothing is
 * numbered, because a number would imply an order the combinator does not give
 * conditions. Where one message could name two conditions of the same kind, the
 * `conditionId` on the choice -- not its wording -- is what locates it. */
export function conditionLabel(kind: ConditionKind | ''): string {
  return kind === '' ? 'Condition' : `${CONDITION_KIND_LABELS[kind]} Condition`;
}

export const ACCRUAL_CONVENTION_LABELS: Readonly<Record<PartnershipAccrualConvention, string>> = {
  simple: 'Simple',
  annual_compound: 'Annual Compound',
};

export const SIMPLE_ORDER_LABELS: Readonly<Record<SimpleDistributionOrder, string>> = {
  accrued_return_first: 'Accrued Return First',
  capital_first: 'Capital First',
};

/** The catch-up recipient kinds. There is deliberately **no** economic-account
 * member: an all-partners recipient would make the target share meaningless,
 * because the recipient's profit would always equal the partnership's
 * (Section 4.3). It is unsupported by design, so it is never offered. */
export const CATCH_UP_RECIPIENT_KIND_LABELS: Readonly<Record<CatchUpRecipientKind, string>> = {
  partner: 'One Partner',
  investor_class: 'An Investor Class',
};

/** The split rules a tier of this kind may take. A `catch_up` tier requires an
 * explicit split (R-D): its rate *is* the recipient's aggregate share there, so
 * a pro-rata split would leave the rate uncheckable before execution. */
export function splitRulesFor(kind: TierKind): SplitRule[] {
  return kind === 'catch_up' ? ['explicit'] : ['explicit', 'pro_rata_by_contribution'];
}

// =============================================================================
// The form
// =============================================================================

/** One partner as the editor holds it. The benchmark share lives here beside
 * the commitment share so the analyst can see the two side by side -- which is
 * exactly what the contract asks the product to disclose -- while remaining a
 * separate, literal, independently typed table (Q2, R-A). */
export interface PartnerForm {
  partnerId: string;
  name: string;
  /** `''` until the analyst states it. Reporting only: it selects nothing. */
  role: PartnerRole | '';
  /** Blank means no class. It is economic wherever a hurdle or catch-up names
   * it. */
  investorClass: string;
  /** A percentage, typed as `90` and sent as `0.9`. */
  commitmentShare: string;
  /** The literal benchmark share, typed independently of the commitment. */
  benchmarkShare: string;
}

/** One hurdle condition as the editor holds it. */
export interface ConditionForm {
  conditionId: string;
  /** `''` until the analyst states it. */
  kind: ConditionKind | '';
  /** IRR only: a percentage, typed as `8` and sent as `0.08`. */
  rate: string;
  /** IRR only; `''` until stated (Q21: never assumed). */
  accrualConvention: PartnershipAccrualConvention | '';
  /** IRR + SIMPLE only; `''` until stated. Forbidden on `annual_compound`. */
  simpleDistributionOrder: SimpleDistributionOrder | '';
  /** MOIC only: a multiple, typed and sent as `1.5`. */
  multiple: string;
}

/** One waterfall tier as the editor holds it. The hurdle fields matter only on
 * a `hurdle` tier and the catch-up fields only on a `catch_up` tier; both are
 * carried on one shape so switching a tier's kind does not discard what the
 * analyst already typed. */
export interface TierForm {
  tierId: string;
  name: string;
  sequence: string;
  kind: TierKind;
  /** `''` until stated. There is no default split rule. */
  splitRule: SplitRule | '';
  /** Explicit split only: one percentage per `partner_id`. */
  splitShares: Record<string, string>;

  /** Hurdle: `''` until stated. */
  subjectKind: HurdleSubjectKind | '';
  subjectPartnerId: string;
  subjectInvestorClass: string;
  subjectAccount: EconomicAccount | '';
  combinator: HurdleCombinator | '';
  conditions: ConditionForm[];

  /** Catch-up: `''` until stated. Never an economic account. */
  recipientKind: CatchUpRecipientKind | '';
  recipientPartnerId: string;
  recipientInvestorClass: string;
  /** A percentage, typed as `20` and sent as `0.2`. */
  targetProfitShare: string;
}

export interface PartnershipForm {
  partners: PartnerForm[];
  /** `''` until stated. One member in v1, and still never assumed. */
  contributionRule: ContributionRule | '';
  /** The stated promote participants. An empty list is a real answer -- but
   * only once `promoteParticipantsConfirmed` says the analyst gave it. */
  promoteParticipantIds: string[];
  /** Whether the analyst has explicitly confirmed the participant set,
   * **including when it is empty** (Q10). Nothing infers it from a role. */
  promoteParticipantsConfirmed: boolean;
  tiers: TierForm[];
}

/** The starting point of a brand-new Partnership: nothing stated, and no
 * partner or tier invented. The editor's Add actions build both. */
export const EMPTY_PARTNERSHIP_FORM: PartnershipForm = {
  partners: [],
  contributionRule: '',
  promoteParticipantIds: [],
  promoteParticipantsConfirmed: false,
  tiers: [],
};

// =============================================================================
// New entities: stable, readable ids, never random
// =============================================================================

function nextId(taken: Iterable<string>, prefix: string): string {
  const used = new Set(taken);
  for (let index = 1; ; index += 1) {
    const candidate = `${prefix}-${index}`;
    if (!used.has(candidate)) {
      return candidate;
    }
  }
}

export function nextPartnerId(form: PartnershipForm): string {
  return nextId(
    form.partners.map((partner) => partner.partnerId),
    'partner',
  );
}

export function nextTierId(form: PartnershipForm): string {
  return nextId(
    form.tiers.map((tier) => tier.tierId),
    'tier',
  );
}

export function nextConditionId(tier: TierForm): string {
  return nextId(
    tier.conditions.map((condition) => condition.conditionId),
    `${tier.tierId}-condition`,
  );
}

/** A new partner with nothing assumed: no role, no commitment and no benchmark
 * share. */
export function newPartner(form: PartnershipForm): PartnerForm {
  return {
    partnerId: nextPartnerId(form),
    name: '',
    role: '',
    investorClass: '',
    commitmentShare: '',
    benchmarkShare: '',
  };
}

/** A new tier of `kind`, with no split rule, no subject and no recipient
 * stated. The sequence is left to the editor's ordering, which states it. */
export function newTier(form: PartnershipForm, kind: TierKind): TierForm {
  return {
    tierId: nextTierId(form),
    name: TIER_KIND_LABELS[kind],
    sequence: '',
    kind,
    splitRule: '',
    splitShares: {},
    subjectKind: '',
    subjectPartnerId: '',
    subjectInvestorClass: '',
    subjectAccount: '',
    combinator: '',
    conditions: [],
    recipientKind: '',
    recipientPartnerId: '',
    recipientInvestorClass: '',
    targetProfitShare: '',
  };
}

/** A new hurdle condition, with no kind and no convention stated. */
export function newCondition(tier: TierForm): ConditionForm {
  return {
    conditionId: nextConditionId(tier),
    kind: '',
    rate: '',
    accrualConvention: '',
    simpleDistributionOrder: '',
    multiple: '',
  };
}

/** The benchmark table as a literal copy of what the analyst typed for the
 * commitments (Section 11.1).
 *
 * This is a **convenience that writes values**, never a link: the two tables
 * stay independent afterwards, and a later change to a commitment does not
 * follow into the benchmark. The engine never equates them either -- it reports
 * `benchmark_equals_commitment` as information only. */
export function withCommitmentsCopiedToBenchmark(form: PartnershipForm): PartnershipForm {
  return {
    ...form,
    partners: form.partners.map((partner) => ({
      ...partner,
      benchmarkShare: partner.commitmentShare,
    })),
  };
}

/** The tier with its split-share table restricted to the current partners: a
 * removed partner's share is dropped, and a new partner's is blank until the
 * analyst types it. It never invents a value for a partner it has not seen. */
export function withSplitSharesForPartners(tier: TierForm, partnerIds: string[]): TierForm {
  const shares: Record<string, string> = {};
  for (const partnerId of partnerIds) {
    shares[partnerId] = tier.splitShares[partnerId] ?? '';
  }
  return { ...tier, splitShares: shares };
}

/** A tier whose kind changed. A catch-up tier may not take a pro-rata split
 * (R-D), so a split rule that the new kind does not permit is dropped back to
 * unstated rather than silently kept as an invalid one. */
export function withTierKind(tier: TierForm, kind: TierKind): TierForm {
  const permitted = splitRulesFor(kind);
  return {
    ...tier,
    kind,
    splitRule:
      tier.splitRule !== '' && permitted.includes(tier.splitRule) ? tier.splitRule : '',
    name: tier.name === TIER_KIND_LABELS[tier.kind] ? TIER_KIND_LABELS[kind] : tier.name,
  };
}

// =============================================================================
// The saved Partnership -> the form
// =============================================================================

function sharesByPartner(rows: PartnerShareRow[]): Record<string, string> {
  const shares: Record<string, string> = {};
  for (const row of rows) {
    shares[row.partner_id] = formatDisplayNumber(row.share * 100);
  }
  return shares;
}

function conditionFormOf(condition: HurdleCondition): ConditionForm {
  if (condition.kind === 'irr') {
    return {
      conditionId: condition.condition_id,
      kind: 'irr',
      rate: formatDisplayNumber(condition.rate * 100),
      accrualConvention: condition.accrual_convention,
      simpleDistributionOrder: condition.simple_distribution_order ?? '',
      multiple: '',
    };
  }
  return {
    conditionId: condition.condition_id,
    kind: 'moic',
    rate: '',
    accrualConvention: '',
    simpleDistributionOrder: '',
    multiple: formatDisplayNumber(condition.multiple),
  };
}

function tierFormOf(tier: WaterfallTier, partnerIds: string[]): TierForm {
  const split = tier.split;
  const explicitShares =
    split !== null && split.kind === 'explicit' ? sharesByPartner(split.shares) : {};
  const splitShares: Record<string, string> = {};
  for (const partnerId of partnerIds) {
    splitShares[partnerId] = explicitShares[partnerId] ?? '';
  }
  const hurdle = tier.hurdle;
  const catchUp = tier.catch_up;
  return {
    tierId: tier.tier_id,
    name: tier.name,
    sequence: formatDisplayNumber(tier.sequence),
    kind: tier.kind,
    splitRule: split === null ? '' : split.kind,
    splitShares,
    subjectKind: hurdle === null ? '' : hurdle.hurdle_subject.kind,
    subjectPartnerId: hurdle === null ? '' : (hurdle.hurdle_subject.partner_id ?? ''),
    subjectInvestorClass: hurdle === null ? '' : (hurdle.hurdle_subject.investor_class ?? ''),
    subjectAccount: hurdle === null ? '' : (hurdle.hurdle_subject.account ?? ''),
    combinator: hurdle === null ? '' : hurdle.combinator,
    conditions: hurdle === null ? [] : hurdle.conditions.map(conditionFormOf),
    recipientKind: catchUp === null ? '' : catchUp.recipient.kind,
    recipientPartnerId: catchUp === null ? '' : (catchUp.recipient.partner_id ?? ''),
    recipientInvestorClass: catchUp === null ? '' : (catchUp.recipient.investor_class ?? ''),
    targetProfitShare: catchUp === null ? '' : formatDisplayNumber(catchUp.target_profit_share * 100),
  };
}

/** The saved Partnership as the editor holds it.
 *
 * Every stable id is kept: reopening a Partnership and saving it again must
 * address the same partners and tiers the Decision Matrix and the fingerprints
 * already know (P-8). A saved Partnership has necessarily been through the
 * Stage 1 validator, so its promote participants are already a stated set --
 * `promoteParticipantsConfirmed` is therefore true on reopen, and the analyst is
 * asked to confirm only a set that has never been stated. */
export function formFromPartnership(partnership: Partnership): PartnershipForm {
  const benchmark = sharesByPartner(partnership.promote_benchmark.shares);
  const partnerIds = partnership.partners.map((partner) => partner.partner_id);
  return {
    partners: partnership.partners.map((partner) => ({
      partnerId: partner.partner_id,
      name: partner.name,
      role: partner.role,
      investorClass: partner.investor_class ?? '',
      commitmentShare: formatDisplayNumber(partner.commitment_share * 100),
      benchmarkShare: benchmark[partner.partner_id] ?? '',
    })),
    contributionRule: partnership.contribution_rule,
    promoteParticipantIds: [...partnership.promote_participant_ids],
    promoteParticipantsConfirmed: true,
    tiers: partnership.tiers.map((tier) => tierFormOf(tier, partnerIds)),
  };
}

// =============================================================================
// The form -> the request
// =============================================================================

function partnerLabel(partner: PartnerForm): string {
  return partner.name.trim() === '' ? partner.partnerId : partner.name.trim();
}

function tierLabel(tier: TierForm): string {
  return tier.name.trim() === '' ? tier.tierId : tier.name.trim();
}

function partnerOf(partner: PartnerForm): Partner {
  const where = partnerLabel(partner);
  if (partner.role === '') {
    throw new Error(`${where}: select a role.`);
  }
  return {
    partner_id: partner.partnerId,
    name: partner.name,
    role: partner.role,
    investor_class: partner.investorClass.trim() === '' ? null : partner.investorClass.trim(),
    commitment_share: parsePercent(`${where} commitment share`, partner.commitmentShare),
  };
}

function splitOf(tier: TierForm, partners: PartnerForm[]): TierSplit | null {
  if (tier.splitRule === '') {
    return null;
  }
  if (tier.splitRule === 'pro_rata_by_contribution') {
    return { kind: 'pro_rata_by_contribution' };
  }
  const where = tierLabel(tier);
  return {
    kind: 'explicit',
    shares: partners.map((partner) => ({
      partner_id: partner.partnerId,
      share: parsePercent(
        `${where}: ${partnerLabel(partner)} share`,
        tier.splitShares[partner.partnerId] ?? '',
      ),
    })),
  };
}

function conditionOf(condition: ConditionForm, where: string): HurdleCondition {
  if (condition.kind === '') {
    throw new Error(`${where}: select a condition type.`);
  }
  if (condition.kind === 'moic') {
    return {
      kind: 'moic',
      condition_id: condition.conditionId,
      multiple: parseNumber(`${where} multiple`, condition.multiple),
    };
  }
  if (condition.accrualConvention === '') {
    throw new Error(`${where}: select an accrual convention.`);
  }
  if (condition.accrualConvention === 'simple' && condition.simpleDistributionOrder === '') {
    throw new Error(`${where}: select a distribution order.`);
  }
  return {
    kind: 'irr',
    condition_id: condition.conditionId,
    rate: parsePercent(`${where} rate`, condition.rate),
    accrual_convention: condition.accrualConvention,
    // Stated only on a SIMPLE condition: an order on an `annual_compound` one
    // is refused by name (`unexpected_simple_distribution_order`).
    simple_distribution_order:
      condition.accrualConvention === 'simple' && condition.simpleDistributionOrder !== ''
        ? condition.simpleDistributionOrder
        : null,
  };
}

function hurdleOf(tier: TierForm): WaterfallTier['hurdle'] {
  if (tier.kind !== 'hurdle') {
    return null;
  }
  const where = tierLabel(tier);
  if (tier.subjectKind === '') {
    throw new Error(`${where}: select whose return the hurdle measures.`);
  }
  if (tier.combinator === '') {
    throw new Error(`${where}: select how the conditions combine.`);
  }
  return {
    hurdle_subject: {
      kind: tier.subjectKind,
      partner_id: tier.subjectKind === 'partner' ? tier.subjectPartnerId : null,
      investor_class:
        tier.subjectKind === 'investor_class' ? tier.subjectInvestorClass.trim() : null,
      account:
        tier.subjectKind === 'economic_account'
          ? (tier.subjectAccount === '' ? null : tier.subjectAccount)
          : null,
    },
    conditions: tier.conditions.map((condition) =>
      conditionOf(condition, `${where} ${conditionLabel(condition.kind)}`),
    ),
    combinator: tier.combinator,
  };
}

function catchUpOf(tier: TierForm): WaterfallTier['catch_up'] {
  if (tier.kind !== 'catch_up') {
    return null;
  }
  const where = tierLabel(tier);
  if (tier.recipientKind === '') {
    throw new Error(`${where}: select who receives the catch-up.`);
  }
  return {
    recipient: {
      kind: tier.recipientKind,
      partner_id: tier.recipientKind === 'partner' ? tier.recipientPartnerId : null,
      investor_class:
        tier.recipientKind === 'investor_class' ? tier.recipientInvestorClass.trim() : null,
    },
    target_profit_share: parsePercent(`${where} target profit share`, tier.targetProfitShare),
  };
}

/** The form as the request the backend validates.
 *
 * Client-side parsing only: a blank or unparsable number, and a choice that has
 * not been stated, are refused here by name before any request is made --
 * exactly as the assumption form refuses one. Every *domain* rule -- shares that
 * must sum to one, exactly one residual holding the last sequence, a subject
 * that must resolve to a partner, a catch-up rate that must exceed its target --
 * belongs to the Stage 1 validator, and its refusals are shown as they arrive.
 *
 * The benchmark is built from what the analyst typed in its own column, never
 * from the commitment shares (Q2). */
export function partnershipFromForm(form: PartnershipForm): Partnership {
  if (form.contributionRule === '') {
    throw new Error('Select a contribution rule.');
  }
  if (!form.promoteParticipantsConfirmed) {
    throw new Error(
      'Confirm which partners earn a promote. Select none if no partner is measured for one.',
    );
  }
  return {
    partners: form.partners.map(partnerOf),
    contribution_rule: form.contributionRule,
    promote_benchmark: {
      shares: form.partners.map((partner) => ({
        partner_id: partner.partnerId,
        share: parsePercent(`${partnerLabel(partner)} benchmark share`, partner.benchmarkShare),
      })),
    },
    promote_participant_ids: [...form.promoteParticipantIds],
    tiers: form.tiers.map((tier) => ({
      tier_id: tier.tierId,
      name: tier.name,
      sequence: parseWholeNumber(`${tierLabel(tier)} sequence`, tier.sequence),
      kind: tier.kind,
      split: splitOf(tier, form.partners),
      hurdle: hurdleOf(tier),
      catch_up: catchUpOf(tier),
    })),
  };
}

// =============================================================================
// What the analyst has not stated yet
// =============================================================================

/** One choice the analyst must still state, and where it belongs.
 *
 * `partnerId`, `tierId` and `conditionId` locate it, because two tiers may carry
 * the same display name -- two hurdles both named "Hurdle" is the ordinary case
 * -- and one tier may be missing both a subject and a split rule at once. The
 * message alone is not unique, so it is not an identity. */
export interface UnstatedPartnershipChoice {
  partnerId: string | null;
  tierId: string | null;
  conditionId: string | null;
  choice:
    | 'contribution_rule'
    | 'promote_participants'
    | 'partner_role'
    | 'benchmark_share'
    | 'split_rule'
    | 'hurdle_subject'
    | 'combinator'
    | 'condition_kind'
    | 'accrual_convention'
    | 'simple_distribution_order'
    | 'catch_up_recipient';
  message: string;
}

/** Everything the analyst must still state before the backend can accept the
 * Partnership.
 *
 * Presentation only -- the Stage 1 validator refuses every one of these anyway,
 * and this only lets the editor say so before the round trip. It reports
 * *unstated choices*, not domain rules: whether the shares sum to one and
 * whether a catch-up rate exceeds its target stay the backend's to judge. */
export function unstatedPartnershipChoices(form: PartnershipForm): UnstatedPartnershipChoice[] {
  const missing: UnstatedPartnershipChoice[] = [];
  const at = (
    choice: UnstatedPartnershipChoice['choice'],
    message: string,
    where: { partnerId?: string; tierId?: string; conditionId?: string } = {},
  ) => {
    missing.push({
      partnerId: where.partnerId ?? null,
      tierId: where.tierId ?? null,
      conditionId: where.conditionId ?? null,
      choice,
      message,
    });
  };

  if (form.contributionRule === '') {
    at('contribution_rule', 'Select a contribution rule.');
  }
  if (!form.promoteParticipantsConfirmed) {
    at(
      'promote_participants',
      'Confirm which partners earn a promote. Select none if no partner is measured for one.',
    );
  }
  for (const partner of form.partners) {
    const name = partnerLabel(partner);
    if (partner.role === '') {
      at('partner_role', `${name}: select a role.`, { partnerId: partner.partnerId });
    }
    if (partner.benchmarkShare.trim() === '') {
      at('benchmark_share', `${name}: state a benchmark share.`, { partnerId: partner.partnerId });
    }
  }
  for (const tier of form.tiers) {
    const name = tierLabel(tier);
    if (tier.splitRule === '') {
      at('split_rule', `${name}: select a split rule.`, { tierId: tier.tierId });
    }
    if (tier.kind === 'hurdle') {
      if (tier.subjectKind === '') {
        at('hurdle_subject', `${name}: select whose return the hurdle measures.`, {
          tierId: tier.tierId,
        });
      }
      if (tier.combinator === '') {
        at('combinator', `${name}: select how the conditions combine.`, { tierId: tier.tierId });
      }
      for (const condition of tier.conditions) {
        const where = { tierId: tier.tierId, conditionId: condition.conditionId };
        const label = `${name} ${conditionLabel(condition.kind)}`;
        if (condition.kind === '') {
          at('condition_kind', `${label}: select a condition type.`, where);
          continue;
        }
        if (condition.kind === 'irr' && condition.accrualConvention === '') {
          at('accrual_convention', `${label}: select an accrual convention.`, where);
        }
        if (
          condition.kind === 'irr' &&
          condition.accrualConvention === 'simple' &&
          condition.simpleDistributionOrder === ''
        ) {
          at('simple_distribution_order', `${label}: select a distribution order.`, where);
        }
      }
    }
    if (tier.kind === 'catch_up' && tier.recipientKind === '') {
      at('catch_up_recipient', `${name}: select who receives the catch-up.`, {
        tierId: tier.tierId,
      });
    }
  }
  return missing;
}
