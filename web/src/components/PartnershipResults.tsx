/**
 * Phase 7 Gate P7.9 Stage 3 -- the Partnership result surface.
 *
 * What the accepted Stage 1 engine produced from this variant's Common Equity
 * Cash Flow: what each partner contributed and was distributed, what it earned,
 * how that compares with the no-promote benchmark, and the tier-by-tier audit
 * behind both.
 *
 * **Every figure is a backend field (P-5).** This component formats and lays
 * out. It sums nothing, allocates nothing, accrues nothing, and derives no
 * comparison: even the difference between a partner's distributions and the
 * benchmark's arrives already computed, because the engine is the one authority
 * on it.
 *
 * **Three concepts, three labels, never blurred** (Q3, R-B):
 *
 * - **Distribution advantage / disadvantage** is total cash above or below the
 *   benchmark, *capital included*. It is never captioned as promote.
 * - **Promote Earned** is profit distributions above the benchmark, *excluding
 *   returned capital*, and is reported only for a stated promote participant. A
 *   partner that is not one reports N/A with the engine's own reason -- never
 *   `0` (R-E, P-9).
 * - **Benchmark capital subordination** is the partner's *own* capital the
 *   benchmark world would have returned and the waterfall did not, because
 *   another claim ranked ahead. Profit a non-participant cedes is not this.
 *
 * There is deliberately no identity between total Promote Earned and total
 * benchmark capital subordination, so they are never totalled together.
 *
 * **The benchmark is independent of the commitments (Q2, R-A).** Where they
 * differ, the surface says so plainly, because the engine never equates them and
 * a reader comparing a partner's ownership with its benchmark must be told.
 *
 * **Honest absences (Section 13).** An unavailable Partnership reports the
 * upstream reason and the Funding Requirements that caused it, with no partner
 * figures at all -- never zeros.
 */

import { irrNotReportedExplanation } from '../capitalEconomics';
import { formatCurrency, formatMultiple, formatPercent } from '../format';
import {
  COMBINATOR_LABELS,
  ECONOMIC_ACCOUNT_LABELS,
  PARTNER_ROLE_LABELS,
  SIMPLE_ORDER_LABELS,
  SPLIT_RULE_LABELS,
  TIER_KIND_LABELS,
} from '../partnershipForm';
import type {
  HurdleAccountRecord,
  HurdleSubject,
  CatchUpRecipient,
  PartnerResult,
  PartnerTierAmount,
  PartnershipResult,
  TierResult,
} from '../partnershipTypes';

export interface PartnershipResultsProps {
  result: PartnershipResult;
  /** The authored partner names, by id. Names are presentation and the result
   * deliberately carries none (Section 12), so they are passed in from the
   * Partnership the analysis resolved. */
  partnerNames: Record<string, string>;
  /** The authored tier names, by id, for the same reason. */
  tierNames: Record<string, string>;
  /** Each hurdle condition's analyst-facing label, by `tier_id` then
   * `condition_id`, resolved from the same Partnership. The opaque
   * `condition_id` keys rows and elements but is never shown. */
  conditionLabels: Record<string, Record<string, string>>;
}

/** Each message is one string literal, never joined with `+`: this module is
 * asserted to contain no binary arithmetic operator, and the audit that forbids
 * browser math cannot tell a concatenated sentence from a sum. */
// prettier-ignore
export const BENCHMARK_MISMATCH_NOTICE =
  'At least one partner’s benchmark share differs from its commitment share. The benchmark is a separate, explicitly stated table; it is never derived from the commitments, and a later change to a commitment does not follow into it.';

/** The compact marker on an affected Benchmark Share cell. The full notice is
 * stated once above the table; repeating it in every cell buried the figures it
 * was meant to qualify. */
// prettier-ignore
export const BENCHMARK_MISMATCH_MARKER =
  'Differs from commitment';

// prettier-ignore
export const BENCHMARK_EXPLAINER =
  'The no-promote benchmark distributes the same cash entirely by the stated benchmark shares, with no tiers, hurdle or catch-up. Contributions are not benchmarked.';

// prettier-ignore
export const ADVANTAGE_EXPLAINER =
  'Total cash above or below the benchmark, returned capital included. This is not promote.';

// prettier-ignore
export const PROMOTE_EXPLAINER =
  'Profit distributions above the no-promote benchmark, excluding returned capital. Reported only for the partners stated as promote participants.';

// prettier-ignore
export const SUBORDINATION_EXPLAINER =
  'The partner’s own capital the benchmark world would have returned, and the waterfall did not, because a claim ahead of it was paid first.';

// prettier-ignore
export const ATTRIBUTION_EXPLAINER =
  'Where each participant’s Promote Earned arose, tier by tier. Values are signed: a tier may carry a negative profit difference inside a positive total.';

// prettier-ignore
export const CADENCE_NOTE =
  'Periods are the annual Common Equity Cash Flow series: period 0 is closing, and each later period is one hold year.';

const NOT_AVAILABLE = 'N/A';

const MOIC_UNAVAILABLE_REASONS: Readonly<Record<string, string>> = {
  no_contributions: 'MOIC is not reported because this partner contributed no capital.',
};

const PROMOTE_UNAVAILABLE_REASONS: Readonly<Record<string, string>> = {
  not_a_promote_participant:
    'Not applicable: this partner is not one of the stated promote participants.',
};

const UPSTREAM_REASONS: Readonly<Record<string, string>> = {
  unresolved_funding_requirement:
    'The Common Equity Cash Flow is unavailable because a Funding Requirement is unresolved.',
};

/** A period's label. The index is the backend's own: `0` is closing and each
 * later index is one hold year. Nothing is computed from it. */
function periodLabel(period: number): string {
  return period === 0 ? 'Closing' : `Year ${period}`;
}

function partnerLabel(partnerId: string, names: Record<string, string>): string {
  const name = names[partnerId];
  return name === undefined || name.trim() === '' ? partnerId : name;
}

/** A tier's label. The Stage 1 result carries no display name -- a financial
 * result deliberately holds none -- so the authored contract's name is used,
 * falling back to the stable id. */
function tierLabel(tierId: string, names: Record<string, string>): string {
  const name = names[tierId];
  return name === undefined || name.trim() === '' ? tierId : name;
}

/** A hurdle condition's label. It never falls back to the opaque id: a
 * condition the contract cannot name is simply "Condition". */
function auditConditionLabel(
  tierId: string,
  conditionId: string,
  labels: Record<string, Record<string, string>>,
): string {
  return labels[tierId]?.[conditionId] ?? 'Condition';
}

/** A tier's account records grouped by condition, in the backend's own order,
 * so each condition's periods read as one account rather than interleaved. */
function recordsByCondition(
  records: HurdleAccountRecord[],
): { conditionId: string; records: HurdleAccountRecord[] }[] {
  const groups: { conditionId: string; records: HurdleAccountRecord[] }[] = [];
  for (const record of records) {
    const group = groups.find((entry) => entry.conditionId === record.condition_id);
    if (group === undefined) {
      groups.push({ conditionId: record.condition_id, records: [record] });
    } else {
      group.records.push(record);
    }
  }
  return groups;
}

/** A backend figure, or `N/A` with the backend's own reason beneath it. */
function Figure({ value, reason }: { value: string | null; reason: string | null }) {
  if (value !== null) {
    return <span className="partner-result-figure">{value}</span>;
  }
  return (
    <>
      <span className="partner-result-na" title={reason ?? undefined}>
        {NOT_AVAILABLE}
      </span>
      {reason !== null && <span className="partner-result-reason">{reason}</span>}
    </>
  );
}

function subjectText(subject: HurdleSubject, names: Record<string, string>): string {
  switch (subject.kind) {
    case 'partner':
      return subject.partner_id === null
        ? 'One partner'
        : partnerLabel(subject.partner_id, names);
    case 'investor_class':
      return subject.investor_class === null
        ? 'An investor class'
        : `Investor class: ${subject.investor_class}`;
    case 'economic_account':
      return subject.account === null
        ? 'An economic account'
        : ECONOMIC_ACCOUNT_LABELS[subject.account];
  }
}

function recipientText(recipient: CatchUpRecipient, names: Record<string, string>): string {
  if (recipient.kind === 'partner') {
    return recipient.partner_id === null ? 'One partner' : partnerLabel(recipient.partner_id, names);
  }
  return recipient.investor_class === null
    ? 'An investor class'
    : `Investor class: ${recipient.investor_class}`;
}

// =============================================================================
// The unavailable state
// =============================================================================

function UnavailablePartnership({ result }: { result: PartnershipResult }) {
  const upstream = result.upstream_reason;
  return (
    <div className="partnership-unavailable" role="status">
      <p className="partnership-unavailable-status">Partnership unavailable</p>
      {result.unavailable_message !== null && (
        <p className="partner-result-reason">{result.unavailable_message}</p>
      )}
      {upstream !== null && (
        <p className="partner-result-reason">
          {UPSTREAM_REASONS[upstream] ?? upstream}
        </p>
      )}
      {result.upstream_requirement_ids.length > 0 && (
        <>
          <p className="partner-result-reason">Unresolved Funding Requirements:</p>
          <ul className="decision-matrix-reasons">
            {result.upstream_requirement_ids.map((requirementId) => (
              <li key={requirementId}>{requirementId}</li>
            ))}
          </ul>
        </>
      )}
      <p className="partner-result-reason">
        No partner figures are reported for an unavailable Common Equity Cash Flow.
      </p>
    </div>
  );
}

// =============================================================================
// Common Equity context
// =============================================================================

function CommonEquityContext({ result }: { result: PartnershipResult }) {
  const periods = result.periods;
  return (
    <section className="partnership-section" aria-labelledby="partnership-common-equity-title">
      <h4 id="partnership-common-equity-title" className="partnership-section-title">
        Common Equity Cash Flow
      </h4>
      <p className="partnership-section-note">{CADENCE_NOTE}</p>
      <dl className="partnership-summary">
        <div className="partnership-summary-item">
          <dt>Common Equity Total Profit</dt>
          <dd>
            <Figure
              value={
                result.common_equity_total_profit === null
                  ? null
                  : formatCurrency(result.common_equity_total_profit)
              }
              reason={null}
            />
          </dd>
        </div>
        <div className="partnership-summary-item">
          <dt>Cadence</dt>
          <dd>Annual</dd>
        </div>
      </dl>
      {periods !== null && (
        <div className="table-scroll">
          <table className="data-table partnership-table partnership-result-table">
            <caption className="visually-hidden">
              The Common Equity Cash Flow by period, with total partner contributions and
              distributions
            </caption>
            <thead>
              <tr>
                <th scope="col" className="partnership-result-identity">Period</th>
                <th scope="col" className="partnership-result-figure">Common Equity Cash Flow</th>
                <th scope="col" className="partnership-result-figure">Contributions</th>
                <th scope="col" className="partnership-result-figure">Distributions</th>
              </tr>
            </thead>
            <tbody>
              {periods.map((record) => (
                <tr key={record.period}>
                  <th scope="row" className="partnership-result-identity">
                    {periodLabel(record.period)}
                  </th>
                  <td className="partnership-result-figure">
                    {formatCurrency(record.common_equity_cash_flow)}
                  </td>
                  <td className="partnership-result-figure">
                    {formatCurrency(record.total_contributions)}
                  </td>
                  <td className="partnership-result-figure">
                    {formatCurrency(record.total_distributions)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// =============================================================================
// Partner returns
// =============================================================================

function PartnerReturnsTable({
  partners,
  names,
}: {
  partners: PartnerResult[];
  names: Record<string, string>;
}) {
  return (
    <section className="partnership-section" aria-labelledby="partnership-returns-title">
      <h4 id="partnership-returns-title" className="partnership-section-title">
        Partner Returns
      </h4>
      {/* Stated once, and only when the engine reports at least one mismatch.
        * `benchmark_equals_commitment` is the backend's own per-partner flag
        * (Q2): this reads it and compares nothing itself. */}
      {partners.some((partner) => !partner.benchmark_equals_commitment) && (
        <p className="partnership-section-note partnership-benchmark-notice" role="note">
          {BENCHMARK_MISMATCH_NOTICE}
        </p>
      )}
      <div className="table-scroll">
        <table className="data-table partnership-table partnership-result-table">
          <caption className="visually-hidden">
            Each partner’s commitment, benchmark share, contributions, distributions and returns
          </caption>
          <thead>
            <tr>
              <th scope="col" className="partnership-result-identity">Partner</th>
              <th scope="col" className="partnership-result-text">Role</th>
              <th scope="col" className="partnership-result-figure">Commitment</th>
              <th scope="col" className="partnership-result-figure">Benchmark Share</th>
              <th scope="col" className="partnership-result-figure">Contributions</th>
              <th scope="col" className="partnership-result-figure">Distributions</th>
              <th scope="col" className="partnership-result-figure">Profit</th>
              <th scope="col" className="partnership-result-figure">Partner IRR</th>
              <th scope="col" className="partnership-result-figure">Partner MOIC</th>
              <th scope="col" className="partnership-result-text">Promote Participant</th>
            </tr>
          </thead>
          <tbody>
            {partners.map((partner) => (
              <tr key={partner.partner_id} data-partner={partner.partner_id}>
                <th scope="row" className="partnership-result-identity">
                  <span className="partner-result-name">
                    {partnerLabel(partner.partner_id, names)}
                  </span>
                  {partner.investor_class !== null && (
                    <span className="partner-result-class">{partner.investor_class}</span>
                  )}
                </th>
                <td className="partnership-result-text">{PARTNER_ROLE_LABELS[partner.role]}</td>
                <td className="partnership-result-figure">
                  {formatPercent(partner.commitment_share)}
                </td>
                <td className="partnership-result-figure" data-field="benchmark_share">
                  {formatPercent(partner.benchmark_share)}
                  {!partner.benchmark_equals_commitment && (
                    <span className="partner-result-mismatch">
                      {BENCHMARK_MISMATCH_MARKER}
                    </span>
                  )}
                </td>
                <td className="partnership-result-figure">
                  {formatCurrency(partner.total_contributions)}
                </td>
                <td className="partnership-result-figure">
                  {formatCurrency(partner.total_distributions)}
                </td>
                <td className="partnership-result-figure">{formatCurrency(partner.profit)}</td>
                <td className="partnership-result-figure" data-field="partner_irr">
                  <Figure
                    value={partner.irr === null ? null : formatPercent(partner.irr)}
                    reason={irrNotReportedExplanation('Partner IRR', partner.irr_status)}
                  />
                </td>
                <td className="partnership-result-figure" data-field="partner_moic">
                  <Figure
                    value={partner.moic === null ? null : formatMultiple(partner.moic)}
                    reason={
                      partner.moic_unavailable_reason === null
                        ? null
                        : (MOIC_UNAVAILABLE_REASONS[partner.moic_unavailable_reason] ??
                          partner.moic_unavailable_reason)
                    }
                  />
                </td>
                <td className="partnership-result-text">
                  {partner.is_promote_participant ? 'Yes' : 'No'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// =============================================================================
// Versus the benchmark: distribution advantage and disadvantage
// =============================================================================

function BenchmarkComparisonTable({
  partners,
  names,
}: {
  partners: PartnerResult[];
  names: Record<string, string>;
}) {
  return (
    <section className="partnership-section" aria-labelledby="partnership-benchmark-title">
      <h4 id="partnership-benchmark-title" className="partnership-section-title">
        Distribution Difference vs Benchmark
      </h4>
      <p className="partnership-section-note">{BENCHMARK_EXPLAINER}</p>
      <p className="partnership-section-note">{ADVANTAGE_EXPLAINER}</p>
      <div className="table-scroll">
        <table className="data-table partnership-table partnership-result-table">
          <caption className="visually-hidden">
            Each partner’s actual and benchmark distributions, and the signed difference split into
            its capital-return and profit-distribution parts
          </caption>
          <thead>
            <tr>
              <th scope="col" className="partnership-result-identity">Partner</th>
              <th scope="col" className="partnership-result-figure">Distributions</th>
              <th scope="col" className="partnership-result-figure">Benchmark Distributions</th>
              <th scope="col" className="partnership-result-figure">Distribution Difference</th>
              <th scope="col" className="partnership-result-figure">Distribution Advantage</th>
              <th scope="col" className="partnership-result-figure">Distribution Disadvantage</th>
              <th scope="col" className="partnership-result-figure">Capital Return Difference</th>
              <th scope="col" className="partnership-result-figure">Profit Distribution Difference</th>
            </tr>
          </thead>
          <tbody>
            {partners.map((partner) => (
              <tr key={partner.partner_id} data-partner={partner.partner_id}>
                <th scope="row" className="partnership-result-identity">
                  {partnerLabel(partner.partner_id, names)}
                </th>
                <td className="partnership-result-figure">
                  {formatCurrency(partner.total_distributions)}
                </td>
                <td className="partnership-result-figure">
                  {formatCurrency(partner.total_benchmark_distributions)}
                </td>
                <td className="partnership-result-figure" data-field="distribution_difference">
                  {formatCurrency(partner.distribution_difference)}
                </td>
                <td className="partnership-result-figure" data-field="distribution_advantage">
                  {formatCurrency(partner.distribution_advantage)}
                </td>
                <td className="partnership-result-figure" data-field="distribution_disadvantage">
                  {formatCurrency(partner.distribution_disadvantage)}
                </td>
                <td className="partnership-result-figure">
                  {formatCurrency(partner.capital_return_difference)}
                </td>
                <td className="partnership-result-figure">
                  {formatCurrency(partner.profit_distribution_difference)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// =============================================================================
// Promote Earned -- its own section, never a caption on an advantage
// =============================================================================

function PromoteEarnedTable({
  partners,
  names,
}: {
  partners: PartnerResult[];
  names: Record<string, string>;
}) {
  return (
    <section className="partnership-section" aria-labelledby="partnership-promote-title">
      <h4 id="partnership-promote-title" className="partnership-section-title">
        Promote Earned
      </h4>
      <p className="partnership-section-note">{PROMOTE_EXPLAINER}</p>
      <div className="table-scroll">
        <table className="data-table partnership-table partnership-result-table">
          <caption className="visually-hidden">
            Promote Earned for each partner, or why it does not apply
          </caption>
          <thead>
            <tr>
              <th scope="col" className="partnership-result-identity">Partner</th>
              <th scope="col" className="partnership-result-text">Promote Participant</th>
              <th scope="col" className="partnership-result-figure">Promote Earned</th>
            </tr>
          </thead>
          <tbody>
            {partners.map((partner) => (
              <tr key={partner.partner_id} data-partner={partner.partner_id}>
                <th scope="row" className="partnership-result-identity">
                  {partnerLabel(partner.partner_id, names)}
                </th>
                <td className="partnership-result-text">
                  {partner.is_promote_participant ? 'Yes' : 'No'}
                </td>
                <td className="partnership-result-figure" data-field="promote_earned">
                  <Figure
                    value={
                      partner.promote_earned === null
                        ? null
                        : formatCurrency(partner.promote_earned)
                    }
                    reason={
                      partner.promote_unavailable_reason === null
                        ? null
                        : (PROMOTE_UNAVAILABLE_REASONS[partner.promote_unavailable_reason] ??
                          partner.promote_unavailable_reason)
                    }
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// =============================================================================
// Benchmark capital subordination -- its own section and its own words
// =============================================================================

function SubordinationTable({
  partners,
  names,
}: {
  partners: PartnerResult[];
  names: Record<string, string>;
}) {
  return (
    <section className="partnership-section" aria-labelledby="partnership-subordination-title">
      <h4 id="partnership-subordination-title" className="partnership-section-title">
        Benchmark Capital Subordination
      </h4>
      <p className="partnership-section-note">{SUBORDINATION_EXPLAINER}</p>
      <div className="table-scroll">
        <table className="data-table partnership-table partnership-result-table">
          <caption className="visually-hidden">
            Each partner’s capital returned against the benchmark world’s, and the resulting
            benchmark capital subordination
          </caption>
          <thead>
            <tr>
              <th scope="col" className="partnership-result-identity">Partner</th>
              <th scope="col" className="partnership-result-figure">Capital Returned</th>
              <th scope="col" className="partnership-result-figure">Benchmark Capital Returned</th>
              <th scope="col" className="partnership-result-figure">Benchmark Capital Subordination</th>
            </tr>
          </thead>
          <tbody>
            {partners.map((partner) => (
              <tr key={partner.partner_id} data-partner={partner.partner_id}>
                <th scope="row" className="partnership-result-identity">
                  {partnerLabel(partner.partner_id, names)}
                </th>
                <td className="partnership-result-figure">
                  {formatCurrency(partner.capital_returned)}
                </td>
                <td className="partnership-result-figure">
                  {formatCurrency(partner.benchmark_capital_returned)}
                </td>
                <td className="partnership-result-figure" data-field="benchmark_capital_subordination">
                  {formatCurrency(partner.benchmark_capital_subordination)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// =============================================================================
// Promote attribution by tier
// =============================================================================

function tierAmount(rows: PartnerTierAmount[] | null, tierId: string): number | null {
  if (rows === null) {
    return null;
  }
  const row = rows.find((entry) => entry.tier_id === tierId);
  return row === undefined ? null : row.amount;
}

function PromoteAttributionTable({
  partners,
  tiers,
  names,
  tierNames,
}: {
  partners: PartnerResult[];
  tiers: TierResult[];
  names: Record<string, string>;
  tierNames: Record<string, string>;
}) {
  const participants = partners.filter((partner) => partner.promote_attribution_by_tier !== null);
  if (participants.length === 0) {
    return (
      <section className="partnership-section" aria-labelledby="partnership-attribution-title">
        <h4 id="partnership-attribution-title" className="partnership-section-title">
          Promote Attribution by Tier
        </h4>
        <p className="scenario-muted">
          No partner is a stated promote participant, so there is no promote to attribute.
        </p>
      </section>
    );
  }
  return (
    <section className="partnership-section" aria-labelledby="partnership-attribution-title">
      <h4 id="partnership-attribution-title" className="partnership-section-title">
        Promote Attribution by Tier
      </h4>
      <p className="partnership-section-note">{ATTRIBUTION_EXPLAINER}</p>
      <div className="table-scroll">
        <table className="data-table partnership-table partnership-result-table">
          <caption className="visually-hidden">
            Each promote participant’s Promote Earned attributed across the waterfall tiers
          </caption>
          <thead>
            <tr>
              <th scope="col" className="partnership-result-identity">Partner</th>
              {tiers.map((tier) => (
                <th key={tier.tier_id} scope="col" className="partnership-result-figure">
                  {tierLabel(tier.tier_id, tierNames)}
                </th>
              ))}
              <th scope="col" className="partnership-result-figure">Promote Earned</th>
            </tr>
          </thead>
          <tbody>
            {participants.map((partner) => (
              <tr key={partner.partner_id} data-partner={partner.partner_id}>
                <th scope="row" className="partnership-result-identity">
                  {partnerLabel(partner.partner_id, names)}
                </th>
                {tiers.map((tier) => {
                  const amount = tierAmount(partner.promote_attribution_by_tier, tier.tier_id);
                  return (
                    <td key={tier.tier_id} className="partnership-result-figure" data-tier={tier.tier_id}>
                      <Figure
                        value={amount === null ? null : formatCurrency(amount)}
                        reason={null}
                      />
                    </td>
                  );
                })}
                <td className="partnership-result-figure" data-field="promote_earned">
                  <Figure
                    value={
                      partner.promote_earned === null
                        ? null
                        : formatCurrency(partner.promote_earned)
                    }
                    reason={null}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// =============================================================================
// The tier audit
// =============================================================================

function TierAudit({
  tiers,
  names,
  tierNames,
  conditionLabels,
}: {
  tiers: TierResult[];
  names: Record<string, string>;
  tierNames: Record<string, string>;
  conditionLabels: Record<string, Record<string, string>>;
}) {
  return (
    <section className="partnership-section" aria-labelledby="partnership-tiers-title">
      <h4 id="partnership-tiers-title" className="partnership-section-title">
        Tier Audit
      </h4>
      {tiers.map((tier) => (
        <article key={tier.tier_id} className="partnership-tier" data-tier={tier.tier_id}>
          <h5 className="partnership-tier-title">
            <span className="partnership-tier-sequence">{tier.sequence}</span>
            <span className="partnership-tier-name">
              {tierLabel(tier.tier_id, tierNames)}
            </span>
            <span className="partnership-tier-kind">{TIER_KIND_LABELS[tier.kind]}</span>
          </h5>
          <dl className="partnership-summary">
            <div className="partnership-summary-item">
              <dt>Split Rule</dt>
              <dd>{SPLIT_RULE_LABELS[tier.split_rule]}</dd>
            </div>
            {tier.hurdle_subject !== null && (
              <div className="partnership-summary-item">
                <dt>Hurdle Subject</dt>
                <dd>{subjectText(tier.hurdle_subject, names)}</dd>
              </div>
            )}
            {tier.combinator !== null && (
              <div className="partnership-summary-item">
                <dt>Conditions Combine</dt>
                <dd>{COMBINATOR_LABELS[tier.combinator]}</dd>
              </div>
            )}
            {tier.catch_up_recipient !== null && (
              <div className="partnership-summary-item">
                <dt>Catch-Up Recipient</dt>
                <dd>{recipientText(tier.catch_up_recipient, names)}</dd>
              </div>
            )}
            {tier.catch_up_rate !== null && (
              <div className="partnership-summary-item">
                <dt>Catch-Up Rate</dt>
                <dd>{formatPercent(tier.catch_up_rate)}</dd>
              </div>
            )}
            {tier.target_profit_share !== null && (
              <div className="partnership-summary-item">
                <dt>Target Profit Share</dt>
                <dd>{formatPercent(tier.target_profit_share)}</dd>
              </div>
            )}
          </dl>

          <h6 className="partnership-audit-subtitle">Distributions by Period</h6>
          <div className="table-scroll">
            <table className="data-table partnership-table partnership-audit-table">
              <caption className="visually-hidden">
                {`${tierLabel(tier.tier_id, tierNames)}: the cash it distributed in each period and the shares it applied`}
              </caption>
              <thead>
                <tr>
                  <th scope="col" className="partnership-audit-period">
                    Period
                  </th>
                  <th scope="col" className="partnership-audit-figure">
                    Tier Distribution
                  </th>
                  <th scope="col" className="partnership-audit-shares">
                    Applied Shares
                  </th>
                </tr>
              </thead>
              <tbody>
                {/* `amounts` is the engine's dense per-period series (index 0 is
                  * closing), while `shares_by_period` lists only the periods the
                  * tier paid. The amount is therefore read by the row's own
                  * period, never by the row's position in this sparse list. */}
                {tier.shares_by_period.map((row) => (
                  <tr key={row.period} data-period={row.period}>
                    <th scope="row" className="partnership-audit-period">
                      {periodLabel(row.period)}
                    </th>
                    <td className="partnership-audit-figure" data-field="tier_amount">
                      <Figure
                        value={
                          tier.amounts[row.period] === undefined
                            ? null
                            : formatCurrency(tier.amounts[row.period])
                        }
                        reason={null}
                      />
                    </td>
                    <td className="partnership-audit-shares">
                      <ul className="partnership-share-list">
                        {row.shares.map((share) => (
                          <li key={share.partner_id}>
                            <span className="partnership-share-name">
                              {partnerLabel(share.partner_id, names)}
                            </span>
                            <span className="partnership-share-value">
                              {formatPercent(share.share)}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {recordsByCondition(tier.conditions).map((group) => {
            const label = auditConditionLabel(tier.tier_id, group.conditionId, conditionLabels);
            return (
              <div
                key={group.conditionId}
                className="partnership-audit-condition"
                data-condition={group.conditionId}
              >
                <h6 className="partnership-audit-subtitle">{`Hurdle Account: ${label}`}</h6>
                <div className="table-scroll">
                  <table className="data-table partnership-table partnership-audit-table">
                    <caption className="visually-hidden">
                      {`${tierLabel(tier.tier_id, tierNames)}: the ${label} account by period`}
                    </caption>
                    <thead>
                      <tr>
                        <th scope="col" className="partnership-audit-period">
                          Period
                        </th>
                        <th scope="col" className="partnership-audit-figure">
                          Opening Balance
                        </th>
                        <th scope="col" className="partnership-audit-figure">
                          Accrual
                        </th>
                        <th scope="col" className="partnership-audit-figure">
                          Subject Contributions
                        </th>
                        <th scope="col" className="partnership-audit-figure">
                          Distributions From Tier
                        </th>
                        <th scope="col" className="partnership-audit-figure">
                          Closing Balance
                        </th>
                        <th scope="col" className="partnership-audit-status">
                          Satisfied
                        </th>
                        <th scope="col" className="partnership-audit-text">
                          Distribution Order
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {group.records.map((record) => (
                        <tr
                          key={`${record.condition_id}|${record.period}`}
                          data-condition={record.condition_id}
                          data-period={record.period}
                        >
                          <th scope="row" className="partnership-audit-period">
                            {periodLabel(record.period)}
                          </th>
                          <td className="partnership-audit-figure">{formatCurrency(record.opening_balance)}</td>
                          <td className="partnership-audit-figure">{formatCurrency(record.accrual)}</td>
                          <td className="partnership-audit-figure">{formatCurrency(record.subject_contributions)}</td>
                          <td className="partnership-audit-figure">
                            {formatCurrency(record.subject_distributions_from_tier)}
                          </td>
                          <td className="partnership-audit-figure">{formatCurrency(record.closing_balance)}</td>
                          <td className="partnership-audit-status">{record.satisfied_at_close ? 'Yes' : 'No'}</td>
                          <td className="partnership-audit-text">
                            {record.simple_distribution_order === null
                              ? NOT_AVAILABLE
                              : SIMPLE_ORDER_LABELS[record.simple_distribution_order]}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            );
          })}

          {tier.catch_up_records.length > 0 && (
            <div className="partnership-audit-condition">
              <h6 className="partnership-audit-subtitle">Catch-Up Account</h6>
              <div className="table-scroll">
                <table className="data-table partnership-table partnership-audit-table">
                  <caption className="visually-hidden">
                    {`${tierLabel(tier.tier_id, tierNames)}: the catch-up account by period`}
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col" className="partnership-audit-period">
                        Period
                      </th>
                      <th scope="col" className="partnership-audit-figure">
                        Partnership Profit at Entry
                      </th>
                      <th scope="col" className="partnership-audit-figure">
                        Recipient Profit at Entry
                      </th>
                      <th scope="col" className="partnership-audit-status">
                        Profit Domain Open
                      </th>
                      <th scope="col" className="partnership-audit-figure">
                        Capacity at Entry
                      </th>
                      <th scope="col" className="partnership-audit-figure">
                        Paid
                      </th>
                      <th scope="col" className="partnership-audit-status">
                        Caught Up
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {tier.catch_up_records.map((record) => (
                      <tr key={record.period}>
                        <th scope="row" className="partnership-audit-period">
                          {periodLabel(record.period)}
                        </th>
                        <td className="partnership-audit-figure">
                          {formatCurrency(record.partnership_profit_at_entry)}
                        </td>
                        <td className="partnership-audit-figure">
                          {formatCurrency(record.recipient_profit_at_entry)}
                        </td>
                        <td className="partnership-audit-status">{record.profit_domain_open ? 'Yes' : 'No'}</td>
                        <td className="partnership-audit-figure">{formatCurrency(record.capacity_at_entry)}</td>
                        <td className="partnership-audit-figure">{formatCurrency(record.paid)}</td>
                        <td className="partnership-audit-status">{record.caught_up ? 'Yes' : 'No'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </article>
      ))}
    </section>
  );
}

// =============================================================================
// The surface
// =============================================================================

export function PartnershipResults({
  result,
  partnerNames,
  tierNames,
  conditionLabels,
}: PartnershipResultsProps) {
  if (result.status === 'unavailable' || result.partners === null) {
    return (
      <div className="partnership-results">
        <UnavailablePartnership result={result} />
      </div>
    );
  }
  const partners = result.partners;
  const tiers = result.tiers ?? [];
  return (
    <div className="partnership-results">
      <p className="partnership-status" role="status">
        Partnership complete
      </p>
      <CommonEquityContext result={result} />
      <PartnerReturnsTable partners={partners} names={partnerNames} />
      <BenchmarkComparisonTable partners={partners} names={partnerNames} />
      <PromoteEarnedTable partners={partners} names={partnerNames} />
      <SubordinationTable partners={partners} names={partnerNames} />
      <PromoteAttributionTable
        partners={partners}
        tiers={tiers}
        names={partnerNames}
        tierNames={tierNames}
      />
      <TierAudit
        tiers={tiers}
        names={partnerNames}
        tierNames={tierNames}
        conditionLabels={conditionLabels}
      />
    </div>
  );
}
