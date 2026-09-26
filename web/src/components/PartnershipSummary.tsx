/**
 * The saved Partnership at a glance: who the partners are and what each
 * committed, who participates in promote, and the waterfall as the ordered
 * run of tiers it is -- each hurdle's test, each catch-up's recipient and
 * target, each tier's split -- stated in words.
 *
 * Presentation only. Every share, rate and multiple is the analyst's own
 * authored value, read back through the editor's form model
 * (`formFromPartnership`, which owns the display-scale conversion) or the
 * existing condition labels, so a term reads here exactly as it was typed.
 * Nothing is derived, totalled or inferred -- in particular nothing is
 * inferred from a partner's role -- and the tiers keep their saved order,
 * each stating its own sequence. What the waterfall *pays* is the engine's,
 * reported by the Partnership Analysis below.
 */

import {
  COMBINATOR_LABELS,
  CONTRIBUTION_RULE_LABELS,
  ECONOMIC_ACCOUNT_LABELS,
  PARTNER_ROLE_LABELS,
  SPLIT_RULE_LABELS,
  TIER_KIND_LABELS,
  conditionAuditLabels,
  formFromPartnership,
} from '../partnershipForm';
import type { PartnerForm, TierForm } from '../partnershipForm';
import type { Partnership, WaterfallTier } from '../partnershipTypes';

export interface PartnershipSummaryProps {
  partnership: Partnership;
}

function shareText(value: string): string {
  return value.trim() === '' ? '—' : `${value.trim()}%`;
}

function partnerName(partners: PartnerForm[], partnerId: string | null): string {
  return partners.find((partner) => partner.partnerId === partnerId)?.name ?? 'A partner';
}

function splitText(tier: TierForm, partners: PartnerForm[]): string {
  if (tier.splitRule === 'explicit') {
    const shares = partners
      .filter((partner) => (tier.splitShares[partner.partnerId] ?? '').trim() !== '')
      .map((partner) => `${partner.name} ${shareText(tier.splitShares[partner.partnerId] ?? '')}`);
    return shares.length === 0 ? SPLIT_RULE_LABELS.explicit : shares.join(' · ');
  }
  return tier.splitRule === '' ? '—' : SPLIT_RULE_LABELS[tier.splitRule];
}

interface TierFact {
  label: string;
  value: string;
}

function tierFacts(
  tier: WaterfallTier,
  form: TierForm,
  partners: PartnerForm[],
  conditionLabels: Record<string, string>,
): TierFact[] {
  const facts: TierFact[] = [];
  if (tier.hurdle !== null) {
    const subject = tier.hurdle.hurdle_subject;
    facts.push({
      label: 'Tested on',
      value:
        subject.kind === 'partner'
          ? partnerName(partners, subject.partner_id)
          : subject.kind === 'investor_class'
            ? `Investor class: ${subject.investor_class ?? '—'}`
            : subject.account === null
              ? '—'
              : ECONOMIC_ACCOUNT_LABELS[subject.account],
    });
    const conditions = tier.hurdle.conditions.map(
      (condition) => conditionLabels[condition.condition_id] ?? 'Condition',
    );
    facts.push({ label: 'Test', value: conditions.length === 0 ? '—' : conditions.join('; ') });
    if (conditions.length > 1) {
      facts.push({ label: 'Conditions', value: COMBINATOR_LABELS[tier.hurdle.combinator] });
    }
  }
  if (tier.catch_up !== null) {
    const recipient = tier.catch_up.recipient;
    facts.push({
      label: 'Catches up',
      value:
        recipient.kind === 'partner'
          ? partnerName(partners, recipient.partner_id)
          : `Investor class: ${recipient.investor_class ?? '—'}`,
    });
    facts.push({ label: 'Target profit share', value: shareText(form.targetProfitShare) });
  }
  facts.push({ label: 'Split', value: splitText(form, partners) });
  return facts;
}

export function PartnershipSummary({ partnership }: PartnershipSummaryProps) {
  const form = formFromPartnership(partnership);
  const tierForms = Object.fromEntries(form.tiers.map((tier) => [tier.tierId, tier] as const));
  const conditionLabels = conditionAuditLabels(partnership);

  return (
    <div className="partnership-summary">
      <section className="partnership-summary-block" aria-label="Saved partners">
        <div className="partnership-summary-head">
          <h4 className="partnership-summary-title">Partners</h4>
          <p className="partnership-summary-note">
            {`Contributions: ${CONTRIBUTION_RULE_LABELS[partnership.contribution_rule]}`}
          </p>
        </div>
        <div className="table-scroll partnership-summary-scroll">
          <table className="partnership-summary-table">
            <thead>
              <tr>
                <th scope="col" className="col-text">
                  Partner
                </th>
                <th scope="col" className="col-text">
                  Investor class
                </th>
                <th scope="col" className="col-num">
                  Commitment
                </th>
                <th scope="col" className="col-num">
                  Benchmark share
                </th>
                <th scope="col" className="col-text">
                  Promote
                </th>
              </tr>
            </thead>
            <tbody>
              {form.partners.map((partner) => (
                <tr key={partner.partnerId}>
                  <th scope="row" className="col-text">
                    <span className="partnership-summary-name">{partner.name}</span>
                    <span className="partnership-summary-role">
                      {partner.role === '' ? '—' : PARTNER_ROLE_LABELS[partner.role]}
                    </span>
                  </th>
                  <td className="col-text" data-label="Investor class">
                    {partner.investorClass.trim() === '' ? '—' : partner.investorClass}
                  </td>
                  <td className="col-num" data-label="Commitment">
                    {shareText(partner.commitmentShare)}
                  </td>
                  <td className="col-num" data-label="Benchmark share">
                    {shareText(partner.benchmarkShare)}
                  </td>
                  <td className="col-text" data-label="Promote">
                    {partnership.promote_participant_ids.includes(partner.partnerId) ? (
                      <span className="ws-tag ws-tag-linked">Promote participant</span>
                    ) : (
                      <span className="partnership-summary-muted">No promote</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="partnership-summary-block">
        <div className="partnership-summary-head">
          <h4 className="partnership-summary-title">Waterfall</h4>
          <p className="partnership-summary-note">Tiers in sequence order.</p>
        </div>
        <ol className="partnership-flow" aria-label="Saved waterfall tiers">
          {partnership.tiers.map((tier) => {
            const tierForm = tierForms[tier.tier_id];
            return (
              <li key={tier.tier_id} className={`partnership-flow-tier partnership-flow-${tier.kind}`}>
                <span className="partnership-flow-sequence" aria-label={`Sequence ${tier.sequence}`}>
                  {tier.sequence}
                </span>
                <div className="partnership-flow-body">
                  <div className="partnership-flow-head">
                    <span className="partnership-flow-name">{tier.name}</span>
                    <span className="ws-tag">{TIER_KIND_LABELS[tier.kind]}</span>
                  </div>
                  {tierForm !== undefined && (
                    <dl className="partnership-flow-facts">
                      {tierFacts(tier, tierForm, form.partners, conditionLabels[tier.tier_id] ?? {}).map(
                        (fact) => (
                          <div key={fact.label}>
                            <dt>{fact.label}</dt>
                            <dd>{fact.value}</dd>
                          </div>
                        ),
                      )}
                    </dl>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      </section>
    </div>
  );
}
