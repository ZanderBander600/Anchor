/**
 * Phase 7 Gate P7.8B -- the Capital Structure editor.
 *
 * The stack of positions above Common Equity, authored whole: each position's
 * class, scope, priority, funding and terms, and how a shortfall of its claim
 * is resolved. Saving replaces the whole structure, exactly as a Strategy
 * overlay replaces a whole domain.
 *
 * **It computes nothing.** Every funded amount, return, attachment, coverage,
 * Funding Requirement and Common Equity figure comes from the backend (P-5).
 * The only conversion here is display scale -- a rate typed as `12.5` is sent
 * as `0.125` -- and it lives in `capitalStructureForm.ts`, with the parsers
 * every assumption field already uses.
 *
 * **No default is invented.** A claim-bearing position starts with no
 * shortfall resolution selected and a preferred position that accrues with no
 * convention, because the engine refuses to assume either (P-14, FR-4). Both
 * read "Choose…", and the editor says what is still unstated before the round
 * trip rather than guessing.
 *
 * **Identity is class and scope (P-8).** Changing either is a different
 * economic instrument, so the form mints a new `position_id` rather than
 * quietly redefining the one the Decision Matrix addresses. The analyst is told
 * so, because the Position perspective they have been comparing is what
 * changes.
 *
 * **The backend owns every domain rule.** Priority within a scope, one identity
 * per position, what the executor can schedule: those refusals arrive from the
 * server and are shown against the position they name, never pre-empted by a
 * second opinion here.
 */

import { useId } from 'react';
import type { ReactNode } from 'react';
import {
  analystCapitalIssues,
  eventFunding,
  eventTimingLabel,
  formEvents,
  isCapitalEventIssue,
  renamePositionReferences,
  withoutPositionReferences,
} from '../capitalEventForm';
import {
  ACCRUAL_CONVENTION_LABELS,
  POSITION_CLASS_LABELS,
  SHORTFALL_RESOLUTION_LABELS,
  isClaimBearing,
  isDebt,
  newPosition,
  unstatedChoices,
  withClassOrScope,
} from '../capitalStructureForm';
import type { CapitalStructureForm, FundingRuleKind, PositionForm } from '../capitalStructureForm';
import type {
  CapitalStructureIssue,
  PositionClass,
  ShortfallResolution,
} from '../capitalTypes';
import { CapitalEventEditor } from './CapitalEventEditor';
import { NumericInput } from './NumericInput';

/** One Unit a position may be scoped to, named as the analyst knows it. */
export interface ScopeUnit {
  unitId: string;
  name: string;
}

export interface CapitalStructureEditorProps {
  /** The id the opening control's `aria-controls` names. */
  id: string;
  /** The element-id prefix, so a Deal's editor and an Investment's never
   * collide while both are mounted. */
  prefix: string;
  form: CapitalStructureForm;
  onChange: (form: CapitalStructureForm) => void;
  /** The backend's own issues from the last refused save. */
  issues: CapitalStructureIssue[];
  /** A refused save's message, above the positions. */
  saveError?: string | null;
  isSaving?: boolean;
  /** Every control that could change the draft is disabled, and Cancel stays
   * available -- the P7.5 editors' rule while the base underwriting is dirty. */
  locked: boolean;
  /** Why it is locked, shown when it is. */
  lockedReason: string | null;
  onSave?: () => void;
  onCancel?: () => void;
  /** The Units a position may be scoped to. A Deal has exactly one. */
  units: ScopeUnit[];
  /** Inside another editor -- a Strategy stating its own whole structure -- so
   * it renders no title and no Save / Cancel of its own: the enclosing editor
   * owns both, and the structure is saved with the Strategy. */
  embedded?: boolean;
  /** Refinance V1 Stage 3: the Investment whose valuations a capital event's
   * LTV constraint may reference, or `null` while there is none. */
  valuationOwnerId?: string | null;
}

/** The classes on offer, in the order an analyst builds a stack. */
const POSITION_CLASSES: PositionClass[] = [
  'senior_debt',
  'mezzanine_debt',
  'preferred_equity',
  'common_equity',
];

const SHORTFALL_RESOLUTIONS: ShortfallResolution[] = ['common_equity_contribution', 'unresolved'];

const ACCRUAL_CONVENTIONS: ('simple' | 'annual_compound')[] = ['simple', 'annual_compound'];

/** Each message is one string literal, never joined with `+`: this module is
 * asserted to contain no binary arithmetic operator, and the audit that forbids
 * browser math cannot tell a concatenated sentence from a sum. */
// prettier-ignore
export const IDENTITY_MOVES_MESSAGE =
  'Changing the class or scope of a position makes it a different instrument, so it is given a new identity. Its position-level comparison starts again from this strategy.';

// prettier-ignore
export const COMMON_EQUITY_MARKER_MESSAGE =
  'Common Equity names the residual. It carries no funding, no terms and no shortfall resolution: it receives what is left after every claim above it.';

// prettier-ignore
export const EMPTY_STRUCTURE_MESSAGE =
  'No structured capital. Each Unit keeps its acquisition loan and the residual, exactly as it is underwritten today.';

// prettier-ignore
export const UNSTATED_CHOICES_TITLE =
  'State these before saving:';

// prettier-ignore
export const EVENT_SAVE_REFUSED_MESSAGE =
  'The capital structure could not be saved. Resolve the issues shown against each item.';

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
  group = false,
  describedBy,
  invalid,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  prefix?: string;
  suffix?: string;
  group?: boolean;
  describedBy?: string;
  invalid?: boolean;
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
          aria-invalid={invalid === true ? true : undefined}
          aria-describedby={describedBy}
          style={{
            paddingLeft: prefix !== undefined ? '1.4rem' : undefined,
            paddingRight: suffix !== undefined ? (suffix.length > 2 ? '2.6rem' : '1.8rem') : undefined,
          }}
        />
        {suffix !== undefined && <span className="field-affix field-affix-right">{suffix}</span>}
      </div>
    </div>
  );
}

function IssueList({ id, issues }: { id: string; issues: CapitalStructureIssue[] }) {
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

interface PositionCardProps {
  form: CapitalStructureForm;
  position: PositionForm;
  index: number;
  prefix: string;
  issues: CapitalStructureIssue[];
  locked: boolean;
  units: ScopeUnit[];
  onChange: (form: CapitalStructureForm) => void;
}

function PositionCard({
  form,
  position,
  index,
  prefix,
  issues,
  locked,
  units,
  onChange,
}: PositionCardProps) {
  const ids = `${prefix}-position-${index}`;
  const issuesId = `${ids}-issues`;
  const describedBy = issues.length > 0 ? issuesId : undefined;
  const claimBearing = isClaimBearing(position.positionClass);
  const debt = isDebt(position.positionClass);
  const preferred = position.positionClass === 'preferred_equity';
  const offersScope = units.length > 1;

  function replace(next: PositionForm) {
    // A class or scope change mints a new identity (P-8); every capital-event
    // reference follows it rather than pointing at an id that is gone.
    onChange(
      renamePositionReferences(
        {
          ...form,
          positions: form.positions.map((candidate) =>
            candidate.positionId === position.positionId ? next : candidate,
          ),
        },
        position.positionId,
        next.positionId,
      ),
    );
  }

  function set<K extends keyof PositionForm>(key: K, value: PositionForm[K]) {
    replace({ ...position, [key]: value });
  }

  function remove() {
    onChange({
      positions: form.positions.filter((candidate) => candidate.positionId !== position.positionId),
      events: withoutPositionReferences(formEvents(form), position.positionId),
    });
  }

  // Refinance V1 Stage 3: a position funded by a capital event states no
  // closing funding of its own. The event sizes its principal.
  const fundingEvent = position.fundingKind === 'capital_event' ? eventFunding(form, position.positionId) : undefined;

  return (
    <fieldset
      className={issues.length > 0 ? 'capital-position capital-position-error' : 'capital-position'}
      aria-describedby={describedBy}
    >
      <legend className="capital-position-legend">
        {position.name.trim() === '' ? POSITION_CLASS_LABELS[position.positionClass] : position.name}
      </legend>

      <div className="capital-position-head">
        <div className="field">
          <label className="field-label" htmlFor={`${ids}-name`}>
            Name
          </label>
          <input
            id={`${ids}-name`}
            className="field-input"
            type="text"
            value={position.name}
            onChange={(event) => set('name', event.target.value)}
            disabled={locked}
            autoComplete="off"
          />
        </div>

        <div className="field">
          <label className="field-label" htmlFor={`${ids}-class`}>
            Class
          </label>
          <select
            id={`${ids}-class`}
            className="field-input scenario-select"
            value={position.positionClass}
            onChange={(event) =>
              replace(
                withClassOrScope(form, position, {
                  positionClass: event.target.value as PositionClass,
                }),
              )
            }
            disabled={locked}
          >
            {POSITION_CLASSES.map((candidate) => (
              <option key={candidate} value={candidate}>
                {POSITION_CLASS_LABELS[candidate]}
              </option>
            ))}
          </select>
        </div>

        {offersScope && (
          <div className="field">
            <label className="field-label" htmlFor={`${ids}-scope`}>
              Scope
            </label>
            <select
              id={`${ids}-scope`}
              className="field-input scenario-select"
              value={position.scopeKind === 'investment' ? 'investment' : (position.scopeUnitId ?? '')}
              onChange={(event) =>
                replace(
                  withClassOrScope(
                    form,
                    position,
                    event.target.value === 'investment'
                      ? { scopeKind: 'investment', scopeUnitId: null }
                      : { scopeKind: 'unit', scopeUnitId: event.target.value },
                  ),
                )
              }
              disabled={locked}
            >
              <option value="investment">Whole Investment</option>
              {units.map((unit) => (
                <option key={unit.unitId} value={unit.unitId}>
                  {unit.name}
                </option>
              ))}
            </select>
          </div>
        )}

        <NumberField
          id={`${ids}-priority`}
          label="Priority"
          value={position.priority}
          onChange={(value) => set('priority', value)}
          disabled={locked}
          describedBy={describedBy}
          invalid={issues.length > 0}
        />
      </div>

      {!claimBearing && <p className="capital-position-note">{COMMON_EQUITY_MARKER_MESSAGE}</p>}

      {claimBearing && (
        <>
          {position.fundingKind === 'capital_event' ? (
            <p className="capital-position-note capital-position-funded-by">
              {fundingEvent === undefined
                ? 'Funded by a capital event. Select this loan as a replacement loan below, or remove it.'
                : `Funded by “${fundingEvent.label.trim() === '' ? 'the capital event' : fundingEvent.label.trim()}”${
                    eventTimingLabel(fundingEvent) === null ? '' : ` at the ${eventTimingLabel(fundingEvent)}`
                  }. Its principal is the gross proceeds that event sizes, and its lender fee is paid on that date.`}
            </p>
          ) : (
          <div className="capital-position-group" role="group" aria-label="Funding">
            <div className="strategy-mode" role="radiogroup" aria-label="Funding amount">
              {(
                [
                  { value: 'fixed_amount', label: 'Fixed Amount' },
                  { value: 'pct_of_price', label: '% of Purchase Price' },
                ] as { value: FundingRuleKind; label: string }[]
              ).map((option) => (
                <label
                  key={option.value}
                  className={
                    option.value === position.fundingKind
                      ? 'strategy-mode-option strategy-mode-option-active'
                      : 'strategy-mode-option'
                  }
                >
                  <input
                    type="radio"
                    name={`${ids}-funding-kind`}
                    value={option.value}
                    checked={option.value === position.fundingKind}
                    disabled={locked}
                    onChange={() => set('fundingKind', option.value)}
                  />
                  <span>{option.label}</span>
                </label>
              ))}
            </div>
            {position.fundingKind === 'pct_of_price' ? (
              <NumberField
                id={`${ids}-funding-pct`}
                label="Funding"
                value={position.fundingPct}
                onChange={(value) => set('fundingPct', value)}
                disabled={locked}
                suffix="%"
              />
            ) : (
              <NumberField
                id={`${ids}-funding-amount`}
                label="Funding"
                value={position.fundingAmount}
                onChange={(value) => set('fundingAmount', value)}
                disabled={locked}
                prefix="$"
                group
              />
            )}
          </div>
          )}

          {debt && (
            <div className="capital-position-fields">
              <NumberField
                id={`${ids}-interest-rate`}
                label="Interest Rate"
                value={position.interestRate}
                onChange={(value) => set('interestRate', value)}
                disabled={locked}
                suffix="%"
              />
              <NumberField
                id={`${ids}-amortization`}
                label="Amortization"
                value={position.amortization}
                onChange={(value) => set('amortization', value)}
                disabled={locked}
                suffix="yrs"
              />
              <NumberField
                id={`${ids}-io-period`}
                label="Interest-Only Period"
                value={position.ioPeriod}
                onChange={(value) => set('ioPeriod', value)}
                disabled={locked}
                suffix="yrs"
              />
              <NumberField
                id={`${ids}-maturity`}
                label="Legal Maturity"
                value={position.maturityMonth}
                onChange={(value) => set('maturityMonth', value)}
                disabled={locked}
                suffix="mo"
              />
              <NumberField
                id={`${ids}-fee-amount`}
                label={position.fundingKind === 'capital_event' ? 'Lender Fee' : 'Closing Fee'}
                value={position.feeAmount}
                onChange={(value) => set('feeAmount', value)}
                disabled={locked}
                prefix="$"
                group
              />
              <div className="field">
                <label className="field-label" htmlFor={`${ids}-fee-description`}>
                  Fee Description
                </label>
                <input
                  id={`${ids}-fee-description`}
                  className="field-input"
                  type="text"
                  value={position.feeDescription}
                  onChange={(event) => set('feeDescription', event.target.value)}
                  disabled={locked || position.feeAmount.trim() === ''}
                  autoComplete="off"
                />
              </div>
            </div>
          )}

          {preferred && (
            <div className="capital-position-fields">
              <NumberField
                id={`${ids}-preferred-rate`}
                label="Preferred Rate"
                value={position.preferredRate}
                onChange={(value) => set('preferredRate', value)}
                disabled={locked}
                suffix="%"
              />
              <NumberField
                id={`${ids}-current-pay-rate`}
                label="Current Pay Rate"
                value={position.currentPayRate}
                onChange={(value) => set('currentPayRate', value)}
                disabled={locked}
                suffix="%"
              />
              <NumberField
                id={`${ids}-redemption`}
                label="Redemption Month"
                value={position.redemptionMonth}
                onChange={(value) => set('redemptionMonth', value)}
                disabled={locked}
                suffix="mo"
              />
              <div className="field capital-position-check">
                <label className="capital-check" htmlFor={`${ids}-accrual-permitted`}>
                  <input
                    id={`${ids}-accrual-permitted`}
                    type="checkbox"
                    checked={position.accrualPermitted}
                    onChange={(event) => set('accrualPermitted', event.target.checked)}
                    disabled={locked}
                  />
                  <span>Unpaid preferred return may accrue</span>
                </label>
              </div>
              {position.accrualPermitted && (
                <div className="field">
                  <label className="field-label" htmlFor={`${ids}-accrual-convention`}>
                    Accrual Convention
                  </label>
                  <select
                    id={`${ids}-accrual-convention`}
                    className="field-input scenario-select"
                    value={position.accrualConvention}
                    onChange={(event) =>
                      set('accrualConvention', event.target.value as 'simple' | 'annual_compound' | '')
                    }
                    disabled={locked}
                  >
                    <option value="">Choose…</option>
                    {ACCRUAL_CONVENTIONS.map((convention) => (
                      <option key={convention} value={convention}>
                        {ACCRUAL_CONVENTION_LABELS[convention]}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          )}

          <div className="field">
            <label className="field-label" htmlFor={`${ids}-shortfall`}>
              If its claim exceeds available cash
            </label>
            <select
              id={`${ids}-shortfall`}
              className="field-input scenario-select"
              value={position.shortfallResolution}
              onChange={(event) =>
                set('shortfallResolution', event.target.value as ShortfallResolution | '')
              }
              disabled={locked}
            >
              <option value="">Choose…</option>
              {SHORTFALL_RESOLUTIONS.map((resolution) => (
                <option key={resolution} value={resolution}>
                  {SHORTFALL_RESOLUTION_LABELS[resolution]}
                </option>
              ))}
            </select>
          </div>
        </>
      )}

      <IssueList id={issuesId} issues={issues} />

      <div className="capital-position-actions">
        <button
          type="button"
          className="btn btn-ghost btn-xs"
          onClick={remove}
          disabled={locked}
          aria-label={`Remove ${position.name.trim() === '' ? position.positionId : position.name}`}
        >
          Remove Position
        </button>
      </div>
    </fieldset>
  );
}

export function CapitalStructureEditor({
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
  units,
  embedded = false,
  valuationOwnerId = null,
}: CapitalStructureEditorProps): ReactNode {
  const titleId = useId();
  const unstated = unstatedChoices(form);
  // Refinance V1 Stage 3: a capital-event refusal names records by their
  // opaque ids, so it is restated in the analyst's terms before it is shown.
  const shown = analystCapitalIssues(issues, form);
  const eventIds = new Set(formEvents(form).map((event) => event.eventId));
  const general = shown.filter((issue) => issue.position_id === null);
  const refusal = shown.some(isCapitalEventIssue) ? EVENT_SAVE_REFUSED_MESSAGE : saveError;
  const defaultScope: { kind: 'unit' | 'investment'; unitId: string | null } =
    units.length === 1 ? { kind: 'unit', unitId: units[0].unitId } : { kind: 'investment', unitId: null };

  function add(positionClass: PositionClass) {
    onChange({ ...form, positions: [...form.positions, newPosition(form, positionClass, defaultScope)] });
  }

  return (
    <section
      id={id}
      className={embedded ? 'capital-editor capital-editor-embedded' : 'scenario-editor capital-editor'}
      aria-labelledby={embedded ? undefined : titleId}
      aria-label={embedded ? 'Capital Structure' : undefined}
    >
      {!embedded && (
        <h4 id={titleId} className="scenario-editor-title">
          Capital Structure
        </h4>
      )}

      {saveError !== null && (
        <div className="error-banner scenario-editor-feedback" role="alert">
          <p className="scenario-editor-feedback-message">{refusal}</p>
          {general.length > 0 && (
            <ul className="scenario-editor-feedback-list">
              {general.map((issue) => (
                <li key={`${issue.code}:${issue.message}`}>{issue.message}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {lockedReason !== null && (
        <p className="scenario-blocked" role="status">
          {lockedReason}
        </p>
      )}

      <p className="strategy-domains-lede">{IDENTITY_MOVES_MESSAGE}</p>

      {form.positions.length === 0 ? (
        <p className="scenario-muted">{EMPTY_STRUCTURE_MESSAGE}</p>
      ) : (
        <div className="capital-positions">
          {form.positions.map((position, index) => (
            <PositionCard
              key={position.positionId}
              form={form}
              position={position}
              index={index}
              prefix={prefix}
              issues={shown.filter((issue) => issue.position_id === position.positionId)}
              locked={locked}
              units={units}
              onChange={onChange}
            />
          ))}
        </div>
      )}

      <div className="capital-add-row" role="group" aria-label="Add a position">
        {POSITION_CLASSES.map((positionClass) => (
          <button
            key={positionClass}
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => add(positionClass)}
            disabled={locked}
          >
            {`Add ${POSITION_CLASS_LABELS[positionClass]}`}
          </button>
        ))}
      </div>

      <CapitalEventEditor
        prefix={prefix}
        form={form}
        onChange={onChange}
        issues={shown.filter((issue) => issue.position_id !== null && (eventIds.has(issue.position_id) || isCapitalEventIssue(issue)))}
        locked={locked}
        units={units}
        valuationOwnerId={valuationOwnerId}
      />

      {unstated.length > 0 && (
        <div className="capital-unstated" role="status">
          <p className="capital-unstated-title">{UNSTATED_CHOICES_TITLE}</p>
          <ul className="capital-unstated-list">
            {/* Keyed by the position and the kind of choice, never by the
              * message: two positions of the same class share a default name,
              * so their messages are identical and a message key collides. */}
            {unstated.map((entry) => (
              <li key={`${entry.positionId}:${entry.choice}`}>{entry.message}</li>
            ))}
          </ul>
        </div>
      )}

      {!embedded && (
        <div className="scenario-editor-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => onCancel?.()}
            disabled={isSaving}
          >
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => onSave?.()}
            disabled={isSaving || locked}
          >
            {isSaving ? 'Saving…' : 'Save Capital Structure'}
          </button>
        </div>
      )}
    </section>
  );
}
