/**
 * Phase 7 Gate P7.9 Stage 3 -- the Partnership editor.
 *
 * The partners, the benchmark, the promote participants and the waterfall
 * tiers, authored whole: saving replaces the whole Partnership, exactly as a
 * Strategy overlay replaces a whole domain.
 *
 * **It computes nothing.** Every contribution, distribution, return, Promote
 * Earned, benchmark capital subordination and tier attribution comes from the
 * accepted Stage 1 engine (P-5). The only conversion here is display scale -- a
 * share typed as `90` is sent as `0.9` -- and it lives in `partnershipForm.ts`,
 * with the parsers every assumption field already uses.
 *
 * **No default is invented** (Section 17.3). The contribution rule, a tier's
 * split rule, a hurdle's subject and combinator, a condition's kind, an IRR
 * condition's accrual convention, a SIMPLE condition's distribution order and a
 * catch-up's recipient all read "Choose…" until the analyst states them. The
 * benchmark is a literal table the analyst types -- the editor offers to copy
 * the commitment shares in as values, which is a convenience, never a link
 * (Q2) -- and the promote participants require an **explicit confirmation, even
 * when the answer is none** (Q10). Nothing is inferred from a partner's role.
 *
 * **Invalid combinations are not offered.** A catch-up recipient is never an
 * economic account, and a catch-up tier never offers a pro-rata split: both are
 * unsupported by design (Section 18), so they are absent from the option lists
 * rather than refused after the fact.
 *
 * **Identity is the id (P-8).** Editing a partner's name, role, class or share,
 * or a tier's name, sequence or terms, keeps its stable id, because the
 * fingerprints and the Partner matrix address it by that id. New ids are minted
 * only for genuinely new partners, tiers and conditions.
 *
 * **The backend owns every domain rule.** Shares that must sum to one, exactly
 * one residual holding the last sequence, a subject that must resolve to a
 * partner, a catch-up rate that must exceed its target: those refusals arrive
 * from the Stage 1 validator and are shown against the partner or tier they
 * name, never pre-empted by a second opinion here.
 */

import {
  ACCRUAL_CONVENTION_LABELS,
  CATCH_UP_RECIPIENT_KIND_LABELS,
  COMBINATOR_LABELS,
  CONDITION_KIND_LABELS,
  conditionLabel,
  CONTRIBUTION_RULE_LABELS,
  ECONOMIC_ACCOUNT_LABELS,
  HURDLE_SUBJECT_KIND_LABELS,
  PARTNER_ROLE_LABELS,
  SIMPLE_ORDER_LABELS,
  SPLIT_RULE_LABELS,
  TIER_KIND_LABELS,
  newCondition,
  newPartner,
  newTier,
  splitRulesFor,
  unstatedPartnershipChoices,
  withCommitmentsCopiedToBenchmark,
  withSplitSharesForPartners,
  withTierKind,
} from '../partnershipForm';
import type {
  ConditionForm,
  ConditionKind,
  PartnerForm,
  PartnershipForm,
  TierForm,
} from '../partnershipForm';
import type {
  CatchUpRecipientKind,
  ContributionRule,
  HurdleCombinator,
  HurdleSubjectKind,
  PartnerRole,
  PartnershipAccrualConvention,
  PartnershipIssue,
  SimpleDistributionOrder,
  TierKind,
} from '../partnershipTypes';
import { NumericInput } from './NumericInput';

export interface PartnershipEditorProps {
  /** The id the opening control's `aria-controls` names. */
  id: string;
  /** The element-id prefix, so a Deal's editor and an Investment's never
   * collide while both are mounted. */
  prefix: string;
  form: PartnershipForm;
  onChange: (form: PartnershipForm) => void;
  /** The backend's own issues from the last refused save. */
  issues: PartnershipIssue[];
  /** A refused save's message, above the partners. */
  saveError?: string | null;
  isSaving?: boolean;
  /** Every control that could change the draft is disabled, and Cancel stays
   * available -- the P7.5 editors' rule while the base underwriting is dirty. */
  locked: boolean;
  /** Why it is locked, shown when it is. */
  lockedReason: string | null;
  onSave?: () => void;
  onCancel?: () => void;
  /** Inside another editor -- a Strategy stating its own whole Partnership --
   * so it renders no title and no Save / Cancel of its own: the enclosing
   * editor owns both, and the Partnership is saved with the Strategy. */
  embedded?: boolean;
}

const PARTNER_ROLES: PartnerRole[] = ['lp', 'gp', 'co_investor'];
const CONTRIBUTION_RULES: ContributionRule[] = ['pro_rata_by_commitment'];
const SUBJECT_KINDS: HurdleSubjectKind[] = ['partner', 'investor_class', 'economic_account'];
const COMBINATORS: HurdleCombinator[] = ['all', 'any'];
const CONDITION_KINDS: ConditionKind[] = ['irr', 'moic'];
const ACCRUAL_CONVENTIONS: PartnershipAccrualConvention[] = ['simple', 'annual_compound'];
const SIMPLE_ORDERS: SimpleDistributionOrder[] = ['accrued_return_first', 'capital_first'];
/** No economic account: an all-partners recipient is unsupported by design. */
const RECIPIENT_KINDS: CatchUpRecipientKind[] = ['partner', 'investor_class'];
const TIER_KINDS: TierKind[] = ['hurdle', 'catch_up', 'residual'];

/** The one unstated-choice placeholder, so every select in this editor says the
 * same thing. */
export const CHOOSE = 'Choose…';

/** Each message is one string literal, never joined with `+`: this module is
 * asserted to contain no binary arithmetic operator, and the audit that forbids
 * browser math cannot tell a concatenated sentence from a sum. */
// prettier-ignore
export const UNSTATED_CHOICES_TITLE =
  'State these before saving:';

// prettier-ignore
export const NO_PARTNERS_MESSAGE =
  'No partners yet. Add at least one partner; a partnership always has one.';

// prettier-ignore
export const NO_TIERS_MESSAGE =
  'No tiers yet. Add the hurdle, catch-up and residual tiers that divide each distribution, in order.';

// prettier-ignore
export const BENCHMARK_EXPLAINER =
  'The no-promote benchmark is a separate table, stated explicitly. It is never derived from the commitment shares, and changing a commitment later does not change it.';

// prettier-ignore
export const COPY_COMMITMENTS_LABEL =
  'Copy commitment shares into the benchmark';

// prettier-ignore
export const PROMOTE_CONFIRM_EXPLAINER =
  'Name every partner whose Promote Earned is reported. Roles infer nothing: a GP that is not named earns no promote, and a partner of any role may be named. Confirm the set even when it is empty.';

// prettier-ignore
export const PROMOTE_CONFIRM_LABEL =
  'I confirm this promote-participant set, including if it is empty';

// prettier-ignore
export const RESIDUAL_EXPLAINER =
  'Exactly one residual tier, holding the last sequence, takes whatever remains in every period.';

// prettier-ignore
export const CATCH_UP_SPLIT_NOTE =
  'A catch-up tier requires explicit shares: its rate is the recipient’s aggregate share here, and it is reported back with the results.';

/** One labelled numeric field, with its units beside the input rather than in
 * the label -- the assumption grid's shape. */
function NumberField({
  id,
  label,
  value,
  onChange,
  disabled,
  prefix,
  suffix,
  describedBy,
  group = false,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  prefix?: string;
  suffix?: string;
  describedBy?: string;
  /** Thousands separators while unfocused. Shares, rates and sequences are
   * small numbers, so they are left ungrouped. */
  group?: boolean;
}) {
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        {label}
      </label>
      <div className="field-input-wrap">
        {prefix !== undefined && <span className="field-affix field-affix-left">{prefix}</span>}
        <NumericInput
          id={id}
          className="field-input"
          value={value}
          onChange={onChange}
          disabled={disabled}
          group={group}
          aria-describedby={describedBy}
          style={{
            paddingLeft: prefix !== undefined ? '1.4rem' : undefined,
            paddingRight: suffix !== undefined ? '1.8rem' : undefined,
          }}
        />
        {suffix !== undefined && <span className="field-affix field-affix-right">{suffix}</span>}
      </div>
    </div>
  );
}

/** One select whose unstated state is a real, selectable "Choose…" option
 * rather than a silently pre-picked first entry. */
function ChoiceField<T extends string>({
  id,
  label,
  value,
  options,
  labels,
  onChange,
  disabled,
  describedBy,
}: {
  id: string;
  label: string;
  value: T | '';
  options: T[];
  labels: Readonly<Record<T, string>>;
  onChange: (value: T | '') => void;
  disabled: boolean;
  describedBy?: string;
}) {
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        {label}
      </label>
      <select
        id={id}
        className="field-input scenario-select"
        value={value}
        onChange={(event) => onChange(event.target.value as T | '')}
        disabled={disabled}
        aria-describedby={describedBy}
      >
        <option value="">{CHOOSE}</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {labels[option]}
          </option>
        ))}
      </select>
    </div>
  );
}

function IssueList({ id, issues }: { id: string; issues: PartnershipIssue[] }) {
  if (issues.length === 0) {
    return null;
  }
  return (
    <ul id={id} className="scenario-override-issues" role="alert">
      {issues.map((issue) => (
        <li key={`${issue.code}:${issue.field ?? ''}:${issue.message}`}>{issue.message}</li>
      ))}
    </ul>
  );
}

function partnerDisplayName(partner: PartnerForm): string {
  return partner.name.trim() === '' ? partner.partnerId : partner.name.trim();
}

function tierDisplayName(tier: TierForm): string {
  return tier.name.trim() === '' ? tier.tierId : tier.name.trim();
}

// =============================================================================
// One partner
// =============================================================================

function PartnerCard({
  form,
  partner,
  prefix,
  issues,
  locked,
  onChange,
}: {
  form: PartnershipForm;
  partner: PartnerForm;
  prefix: string;
  issues: PartnershipIssue[];
  locked: boolean;
  onChange: (form: PartnershipForm) => void;
}) {
  const ids = `${prefix}-partner-${partner.partnerId}`;
  const issuesId = `${ids}-issues`;
  const describedBy = issues.length > 0 ? issuesId : undefined;

  function set<K extends keyof PartnerForm>(key: K, value: PartnerForm[K]) {
    onChange({
      ...form,
      partners: form.partners.map((candidate) =>
        candidate.partnerId === partner.partnerId ? { ...candidate, [key]: value } : candidate,
      ),
    });
  }

  /** Removing a partner removes it everywhere it is addressed: its explicit
   * split shares, and its place in the promote-participant set. Leaving a
   * stale reference behind would be refused by the validator anyway, and
   * silently keeping one would be worse. */
  function remove() {
    const remaining = form.partners.filter(
      (candidate) => candidate.partnerId !== partner.partnerId,
    );
    const remainingIds = remaining.map((candidate) => candidate.partnerId);
    onChange({
      ...form,
      partners: remaining,
      promoteParticipantIds: form.promoteParticipantIds.filter(
        (participantId) => participantId !== partner.partnerId,
      ),
      tiers: form.tiers.map((tier) => withSplitSharesForPartners(tier, remainingIds)),
    });
  }

  return (
    <fieldset
      className={issues.length > 0 ? 'partnership-partner partnership-partner-error' : 'partnership-partner'}
      aria-describedby={describedBy}
    >
      <legend className="partnership-partner-legend">{partnerDisplayName(partner)}</legend>

      <div className="partnership-partner-grid">
        <div className="field">
          <label className="field-label" htmlFor={`${ids}-name`}>
            Name
          </label>
          <input
            id={`${ids}-name`}
            className="field-input"
            type="text"
            value={partner.name}
            onChange={(event) => set('name', event.target.value)}
            disabled={locked}
            autoComplete="off"
          />
        </div>

        <ChoiceField
          id={`${ids}-role`}
          label="Role (reporting only)"
          value={partner.role}
          options={PARTNER_ROLES}
          labels={PARTNER_ROLE_LABELS}
          onChange={(value) => set('role', value)}
          disabled={locked}
          describedBy={describedBy}
        />

        <div className="field">
          <label className="field-label" htmlFor={`${ids}-class`}>
            Investor Class
          </label>
          <input
            id={`${ids}-class`}
            className="field-input"
            type="text"
            value={partner.investorClass}
            onChange={(event) => set('investorClass', event.target.value)}
            disabled={locked}
            autoComplete="off"
            placeholder="None"
          />
        </div>

        <NumberField
          id={`${ids}-commitment`}
          label="Commitment Share"
          value={partner.commitmentShare}
          onChange={(value) => set('commitmentShare', value)}
          disabled={locked}
          suffix="%"
          describedBy={describedBy}
        />

        <NumberField
          id={`${ids}-benchmark`}
          label="Benchmark Share"
          value={partner.benchmarkShare}
          onChange={(value) => set('benchmarkShare', value)}
          disabled={locked}
          suffix="%"
          describedBy={describedBy}
        />
      </div>

      <IssueList id={issuesId} issues={issues} />

      <div className="partnership-card-actions">
        <button
          type="button"
          className="btn btn-ghost btn-xs"
          onClick={remove}
          disabled={locked}
        >
          {`Remove ${partnerDisplayName(partner)}`}
        </button>
      </div>
    </fieldset>
  );
}

// =============================================================================
// One hurdle condition
// =============================================================================

function ConditionCard({
  tier,
  condition,
  prefix,
  locked,
  onChange,
}: {
  tier: TierForm;
  condition: ConditionForm;
  prefix: string;
  locked: boolean;
  onChange: (tier: TierForm) => void;
}) {
  const ids = `${prefix}-condition-${condition.conditionId}`;

  function set<K extends keyof ConditionForm>(key: K, value: ConditionForm[K]) {
    onChange({
      ...tier,
      conditions: tier.conditions.map((candidate) =>
        candidate.conditionId === condition.conditionId
          ? { ...candidate, [key]: value }
          : candidate,
      ),
    });
  }

  function remove() {
    onChange({
      ...tier,
      conditions: tier.conditions.filter(
        (candidate) => candidate.conditionId !== condition.conditionId,
      ),
    });
  }

  return (
    <fieldset className="partnership-condition">
      <legend className="partnership-condition-legend">
        {conditionLabel(condition.kind)}
      </legend>

      <div className="partnership-condition-grid">
        <ChoiceField
          id={`${ids}-kind`}
          label="Condition"
          value={condition.kind}
          options={CONDITION_KINDS}
          labels={CONDITION_KIND_LABELS}
          onChange={(value) => set('kind', value)}
          disabled={locked}
        />

        {condition.kind === 'irr' && (
          <NumberField
            id={`${ids}-rate`}
            label="Rate"
            value={condition.rate}
            onChange={(value) => set('rate', value)}
            disabled={locked}
            suffix="%"
          />
        )}

        {condition.kind === 'irr' && (
          <ChoiceField
            id={`${ids}-accrual`}
            label="Accrual Convention"
            value={condition.accrualConvention}
            options={ACCRUAL_CONVENTIONS}
            labels={ACCRUAL_CONVENTION_LABELS}
            onChange={(value) => set('accrualConvention', value)}
            disabled={locked}
          />
        )}

        {/* Stated only on a SIMPLE condition. An `annual_compound` condition
          * that carries one is refused by name, so the control is not offered
          * there at all. */}
        {condition.kind === 'irr' && condition.accrualConvention === 'simple' && (
          <ChoiceField
            id={`${ids}-order`}
            label="Distribution Order"
            value={condition.simpleDistributionOrder}
            options={SIMPLE_ORDERS}
            labels={SIMPLE_ORDER_LABELS}
            onChange={(value) => set('simpleDistributionOrder', value)}
            disabled={locked}
          />
        )}

        {condition.kind === 'moic' && (
          <NumberField
            id={`${ids}-multiple`}
            label="Multiple"
            value={condition.multiple}
            onChange={(value) => set('multiple', value)}
            disabled={locked}
            suffix="x"
          />
        )}
      </div>

      <div className="partnership-card-actions">
        <button type="button" className="btn btn-ghost btn-xs" onClick={remove} disabled={locked}>
          Remove condition
        </button>
      </div>
    </fieldset>
  );
}

// =============================================================================
// One tier
// =============================================================================

function TierCard({
  form,
  tier,
  prefix,
  issues,
  locked,
  onChange,
}: {
  form: PartnershipForm;
  tier: TierForm;
  prefix: string;
  issues: PartnershipIssue[];
  locked: boolean;
  onChange: (form: PartnershipForm) => void;
}) {
  const ids = `${prefix}-tier-${tier.tierId}`;
  const issuesId = `${ids}-issues`;
  const describedBy = issues.length > 0 ? issuesId : undefined;

  function replace(next: TierForm) {
    onChange({
      ...form,
      tiers: form.tiers.map((candidate) => (candidate.tierId === tier.tierId ? next : candidate)),
    });
  }

  function set<K extends keyof TierForm>(key: K, value: TierForm[K]) {
    replace({ ...tier, [key]: value });
  }

  function setShare(partnerId: string, value: string) {
    replace({ ...tier, splitShares: { ...tier.splitShares, [partnerId]: value } });
  }

  function remove() {
    onChange({
      ...form,
      tiers: form.tiers.filter((candidate) => candidate.tierId !== tier.tierId),
    });
  }

  const splitRules = splitRulesFor(tier.kind);
  const splitLabels: Readonly<Record<string, string>> = SPLIT_RULE_LABELS;

  return (
    <fieldset
      className={issues.length > 0 ? 'partnership-tier-card partnership-tier-card-error' : 'partnership-tier-card'}
      aria-describedby={describedBy}
    >
      <legend className="partnership-tier-legend">{tierDisplayName(tier)}</legend>

      <div className="partnership-tier-grid">
        <div className="field">
          <label className="field-label" htmlFor={`${ids}-name`}>
            Name
          </label>
          <input
            id={`${ids}-name`}
            className="field-input"
            type="text"
            value={tier.name}
            onChange={(event) => set('name', event.target.value)}
            disabled={locked}
            autoComplete="off"
          />
        </div>

        <div className="field">
          <label className="field-label" htmlFor={`${ids}-kind`}>
            Tier
          </label>
          <select
            id={`${ids}-kind`}
            className="field-input scenario-select"
            value={tier.kind}
            onChange={(event) => replace(withTierKind(tier, event.target.value as TierKind))}
            disabled={locked}
          >
            {TIER_KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {TIER_KIND_LABELS[kind]}
              </option>
            ))}
          </select>
        </div>

        <NumberField
          id={`${ids}-sequence`}
          label="Sequence"
          value={tier.sequence}
          onChange={(value) => set('sequence', value)}
          disabled={locked}
          describedBy={describedBy}
        />

        <ChoiceField
          id={`${ids}-split`}
          label="Split Rule"
          value={tier.splitRule}
          options={splitRules}
          labels={splitLabels as Readonly<Record<(typeof splitRules)[number], string>>}
          onChange={(value) => set('splitRule', value)}
          disabled={locked}
          describedBy={describedBy}
        />
      </div>

      {tier.kind === 'catch_up' && (
        <p className="partnership-section-note">{CATCH_UP_SPLIT_NOTE}</p>
      )}

      {tier.kind === 'residual' && <p className="partnership-section-note">{RESIDUAL_EXPLAINER}</p>}

      {tier.splitRule === 'explicit' && (
        <div className="partnership-split-shares">
          <p className="field-label">Shares</p>
          {form.partners.length === 0 ? (
            <p className="scenario-muted">{NO_PARTNERS_MESSAGE}</p>
          ) : (
            <div className="partnership-share-grid">
              {form.partners.map((partner) => (
                <NumberField
                  key={partner.partnerId}
                  id={`${ids}-share-${partner.partnerId}`}
                  label={partnerDisplayName(partner)}
                  value={tier.splitShares[partner.partnerId] ?? ''}
                  onChange={(value) => setShare(partner.partnerId, value)}
                  disabled={locked}
                  suffix="%"
                  describedBy={describedBy}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {tier.kind === 'hurdle' && (
        <div className="partnership-tier-terms">
          <ChoiceField
            id={`${ids}-subject-kind`}
            label="Hurdle Subject"
            value={tier.subjectKind}
            options={SUBJECT_KINDS}
            labels={HURDLE_SUBJECT_KIND_LABELS}
            onChange={(value) => set('subjectKind', value)}
            disabled={locked}
            describedBy={describedBy}
          />

          {tier.subjectKind === 'partner' && (
            <div className="field">
              <label className="field-label" htmlFor={`${ids}-subject-partner`}>
                Partner
              </label>
              <select
                id={`${ids}-subject-partner`}
                className="field-input scenario-select"
                value={tier.subjectPartnerId}
                onChange={(event) => set('subjectPartnerId', event.target.value)}
                disabled={locked}
              >
                <option value="">{CHOOSE}</option>
                {form.partners.map((partner) => (
                  <option key={partner.partnerId} value={partner.partnerId}>
                    {partnerDisplayName(partner)}
                  </option>
                ))}
              </select>
            </div>
          )}

          {tier.subjectKind === 'investor_class' && (
            <div className="field">
              <label className="field-label" htmlFor={`${ids}-subject-class`}>
                Investor Class
              </label>
              <input
                id={`${ids}-subject-class`}
                className="field-input"
                type="text"
                value={tier.subjectInvestorClass}
                onChange={(event) => set('subjectInvestorClass', event.target.value)}
                disabled={locked}
                autoComplete="off"
              />
            </div>
          )}

          {tier.subjectKind === 'economic_account' && (
            <ChoiceField
              id={`${ids}-subject-account`}
              label="Account"
              value={tier.subjectAccount}
              options={['all_common_equity']}
              labels={ECONOMIC_ACCOUNT_LABELS}
              onChange={(value) => set('subjectAccount', value)}
              disabled={locked}
            />
          )}

          <ChoiceField
            id={`${ids}-combinator`}
            label="Conditions Combine"
            value={tier.combinator}
            options={COMBINATORS}
            labels={COMBINATOR_LABELS}
            onChange={(value) => set('combinator', value)}
            disabled={locked}
            describedBy={describedBy}
          />

          <div className="partnership-conditions">
            {tier.conditions.map((condition) => (
              <ConditionCard
                key={condition.conditionId}
                tier={tier}
                condition={condition}
                prefix={ids}
                locked={locked}
                onChange={replace}
              />
            ))}
            <button
              type="button"
              className="btn btn-secondary btn-xs"
              onClick={() => replace({ ...tier, conditions: [...tier.conditions, newCondition(tier)] })}
              disabled={locked}
            >
              Add condition
            </button>
          </div>
        </div>
      )}

      {tier.kind === 'catch_up' && (
        <div className="partnership-tier-terms">
          <ChoiceField
            id={`${ids}-recipient-kind`}
            label="Catch-Up Recipient"
            value={tier.recipientKind}
            options={RECIPIENT_KINDS}
            labels={CATCH_UP_RECIPIENT_KIND_LABELS}
            onChange={(value) => set('recipientKind', value)}
            disabled={locked}
            describedBy={describedBy}
          />

          {tier.recipientKind === 'partner' && (
            <div className="field">
              <label className="field-label" htmlFor={`${ids}-recipient-partner`}>
                Partner
              </label>
              <select
                id={`${ids}-recipient-partner`}
                className="field-input scenario-select"
                value={tier.recipientPartnerId}
                onChange={(event) => set('recipientPartnerId', event.target.value)}
                disabled={locked}
              >
                <option value="">{CHOOSE}</option>
                {form.partners.map((partner) => (
                  <option key={partner.partnerId} value={partner.partnerId}>
                    {partnerDisplayName(partner)}
                  </option>
                ))}
              </select>
            </div>
          )}

          {tier.recipientKind === 'investor_class' && (
            <div className="field">
              <label className="field-label" htmlFor={`${ids}-recipient-class`}>
                Investor Class
              </label>
              <input
                id={`${ids}-recipient-class`}
                className="field-input"
                type="text"
                value={tier.recipientInvestorClass}
                onChange={(event) => set('recipientInvestorClass', event.target.value)}
                disabled={locked}
                autoComplete="off"
              />
            </div>
          )}

          <NumberField
            id={`${ids}-target`}
            label="Target Profit Share"
            value={tier.targetProfitShare}
            onChange={(value) => set('targetProfitShare', value)}
            disabled={locked}
            suffix="%"
            describedBy={describedBy}
          />
        </div>
      )}

      <IssueList id={issuesId} issues={issues} />

      <div className="partnership-card-actions">
        <button type="button" className="btn btn-ghost btn-xs" onClick={remove} disabled={locked}>
          {`Remove ${tierDisplayName(tier)}`}
        </button>
      </div>
    </fieldset>
  );
}

// =============================================================================
// The editor
// =============================================================================

export function PartnershipEditor({
  id,
  prefix,
  form,
  onChange,
  issues,
  saveError = null,
  isSaving = false,
  locked,
  lockedReason,
  onSave,
  onCancel,
  embedded = false,
}: PartnershipEditorProps) {
  const unstated = unstatedPartnershipChoices(form);
  const partnerIds = form.partners.map((partner) => partner.partnerId);

  /** A refusal that names a partner or tier belongs to that card; everything
   * else stays at the top of the editor. */
  function issuesFor(where: { partnerId?: string; tierId?: string }): PartnershipIssue[] {
    return issues.filter((issue) =>
      where.partnerId !== undefined
        ? issue.partner_id === where.partnerId && issue.tier_id === null
        : issue.tier_id === where.tierId,
    );
  }

  const generalIssues = issues.filter(
    (issue) =>
      (issue.partner_id === null || !partnerIds.includes(issue.partner_id)) &&
      (issue.tier_id === null || !form.tiers.some((tier) => tier.tierId === issue.tier_id)),
  );

  function addPartner() {
    const partner = newPartner(form);
    onChange({
      ...form,
      partners: [...form.partners, partner],
      // A new partner has no share in any tier until the analyst states one,
      // and is not a promote participant until the set is stated again.
      tiers: form.tiers.map((tier) =>
        withSplitSharesForPartners(tier, [...partnerIds, partner.partnerId]),
      ),
    });
  }

  function addTier(kind: TierKind) {
    onChange({ ...form, tiers: [...form.tiers, withSplitSharesForPartners(newTier(form, kind), partnerIds)] });
  }

  function toggleParticipant(partnerId: string, checked: boolean) {
    onChange({
      ...form,
      promoteParticipantIds: checked
        ? [...form.promoteParticipantIds, partnerId]
        : form.promoteParticipantIds.filter((candidate) => candidate !== partnerId),
      // Changing the set un-confirms it: the confirmation is of a specific
      // answer, not a box that stays ticked while the answer moves.
      promoteParticipantsConfirmed: false,
    });
  }

  return (
    <div id={id} className="partnership-editor">
      {!embedded && <h4 className="partnership-editor-title">Partnership</h4>}

      {lockedReason !== null && locked && (
        <p className="scenario-blocked" role="status">
          {lockedReason}
        </p>
      )}

      {saveError !== null && (
        <div className="error-banner scenario-error" role="alert">
          <span>{saveError}</span>
        </div>
      )}

      {generalIssues.length > 0 && (
        <ul className="scenario-override-issues" role="alert">
          {generalIssues.map((issue) => (
            <li key={`${issue.code}:${issue.field ?? ''}:${issue.message}`}>{issue.message}</li>
          ))}
        </ul>
      )}

      {unstated.length > 0 && (
        <div className="partnership-unstated" role="status">
          <p className="partnership-unstated-title">{UNSTATED_CHOICES_TITLE}</p>
          <ul className="partnership-unstated-list">
            {unstated.map((choice) => (
              <li
                key={`${choice.choice}:${choice.partnerId ?? ''}:${choice.tierId ?? ''}:${choice.conditionId ?? ''}`}
              >
                {choice.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      <section className="partnership-editor-section" aria-label="Partners">
        <div className="partnership-editor-section-head">
          <h5 className="partnership-editor-section-title">Partners</h5>
          <button
            type="button"
            className="btn btn-secondary btn-xs"
            onClick={addPartner}
            disabled={locked}
          >
            Add partner
          </button>
        </div>

        {form.partners.length === 0 ? (
          <p className="scenario-muted">{NO_PARTNERS_MESSAGE}</p>
        ) : (
          form.partners.map((partner) => (
            <PartnerCard
              key={partner.partnerId}
              form={form}
              partner={partner}
              prefix={prefix}
              issues={issuesFor({ partnerId: partner.partnerId })}
              locked={locked}
              onChange={onChange}
            />
          ))
        )}

        <p className="partnership-section-note">{BENCHMARK_EXPLAINER}</p>
        <button
          type="button"
          className="btn btn-ghost btn-xs partnership-copy-benchmark"
          onClick={() => onChange(withCommitmentsCopiedToBenchmark(form))}
          disabled={locked || form.partners.length === 0}
        >
          {COPY_COMMITMENTS_LABEL}
        </button>
      </section>

      <section className="partnership-editor-section" aria-label="Contribution rule">
        <ChoiceField
          id={`${prefix}-contribution-rule`}
          label="Contribution Rule"
          value={form.contributionRule}
          options={CONTRIBUTION_RULES}
          labels={CONTRIBUTION_RULE_LABELS}
          onChange={(value) => onChange({ ...form, contributionRule: value })}
          disabled={locked}
        />
      </section>

      <section className="partnership-editor-section" aria-label="Promote participants">
        <h5 className="partnership-editor-section-title">Promote Participants</h5>
        <p className="partnership-section-note">{PROMOTE_CONFIRM_EXPLAINER}</p>

        {form.partners.length === 0 ? (
          <p className="scenario-muted">{NO_PARTNERS_MESSAGE}</p>
        ) : (
          <ul className="partnership-participant-list">
            {form.partners.map((partner) => (
              <li key={partner.partnerId}>
                <label className="partnership-checkbox">
                  <input
                    type="checkbox"
                    checked={form.promoteParticipantIds.includes(partner.partnerId)}
                    onChange={(event) => toggleParticipant(partner.partnerId, event.target.checked)}
                    disabled={locked}
                  />
                  <span>{partnerDisplayName(partner)}</span>
                </label>
              </li>
            ))}
          </ul>
        )}

        <label className="partnership-checkbox partnership-confirm">
          <input
            id={`${prefix}-promote-confirm`}
            type="checkbox"
            checked={form.promoteParticipantsConfirmed}
            onChange={(event) =>
              onChange({ ...form, promoteParticipantsConfirmed: event.target.checked })
            }
            disabled={locked}
          />
          <span>{PROMOTE_CONFIRM_LABEL}</span>
        </label>
      </section>

      <section className="partnership-editor-section" aria-label="Waterfall tiers">
        <div className="partnership-editor-section-head">
          <h5 className="partnership-editor-section-title">Waterfall Tiers</h5>
          <div className="partnership-add-tiers">
            {TIER_KINDS.map((kind) => (
              <button
                key={kind}
                type="button"
                className="btn btn-secondary btn-xs"
                onClick={() => addTier(kind)}
                disabled={locked}
              >
                {`Add ${TIER_KIND_LABELS[kind]}`}
              </button>
            ))}
          </div>
        </div>

        {form.tiers.length === 0 ? (
          <p className="scenario-muted">{NO_TIERS_MESSAGE}</p>
        ) : (
          form.tiers.map((tier) => (
            <TierCard
              key={tier.tierId}
              form={form}
              tier={tier}
              prefix={prefix}
              issues={issuesFor({ tierId: tier.tierId })}
              locked={locked}
              onChange={onChange}
            />
          ))
        )}
      </section>

      {!embedded && (
        <div className="scenario-editor-actions">
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={onSave}
            disabled={locked || isSaving}
          >
            {isSaving ? 'Saving…' : 'Save Partnership'}
          </button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
