/**
 * Refinance & Capital Events V1 Stage 3 -- the refinance editor.
 *
 * Authors each refinance of the Capital Structure being edited: its scope, the
 * hold year it occurs at the end of, the loans it repays, the replacement loan
 * it funds, the sizing constraints the lender applies, the valuation an LTV
 * constraint is measured against, and its fixed-dollar costs
 * (`docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md` Sections 6 and 16.3).
 *
 * **It computes nothing.** No capacity, payoff, fee total or net cash is
 * derived here: every figure comes from the engine after the structure is
 * saved and analysed. The only conversions are the display-scale ones in
 * `capitalEventForm.ts`.
 *
 * **The replacement loan is an ordinary position.** It is added to the stack
 * above as a debt position funded by this refinance, and its rate,
 * amortization, interest-only period, legal maturity and lender fee are edited
 * on its own position card, exactly like every other loan (R-G).
 *
 * **A valuation only while LTV is enabled.** The valuation selector exists only
 * inside the enabled LTV constraint. A DSCR-only, fixed-only or fixed-plus-DSCR
 * refinance shows no valuation control at all, because it consumes none (R-C).
 *
 * **Removal is confirmed in the application.** The confirmation focuses the
 * safe action, traps focus, closes on Escape, returns focus to the control that
 * opened it and changes nothing on cancel.
 *
 * **No identity is shown.** Loans are named by their names, Units by their
 * Deal names, valuations by their labels and refinances by their own labels.
 */

import { useEffect, useId, useRef, useState } from 'react';
import {
  EVENT_YEARS,
  endOfYearLabel,
  eventYearOfMonth,
  formEvents,
  legacyKey,
  newCapitalEvent,
  newCostLine,
  positionKey,
  unstatedEventChoices,
  withLtvEnabled,
  withRetiring,
  withoutPositionReferences,
} from '../capitalEventForm';
import type { CapitalEventForm, CostLineForm, RetiringKey } from '../capitalEventForm';
import { POSITION_CLASS_LABELS, isDebt, newPosition } from '../capitalStructureForm';
import type { CapitalStructureForm, PositionForm } from '../capitalStructureForm';
import type { CapitalStructureIssue, RefinanceCostKind } from '../capitalTypes';
import { useValuationChoices } from '../useCapitalEventChoices';
import type { ValuationChoice } from '../useCapitalEventChoices';
import type { ScopeUnit } from './CapitalStructureEditor';
import { ConfirmDialog } from './ConfirmDialog';
import { NumericInput } from './NumericInput';

export interface CapitalEventEditorProps {
  prefix: string;
  form: CapitalStructureForm;
  onChange: (form: CapitalStructureForm) => void;
  /** The backend's issues, already restated in the analyst's terms. */
  issues: CapitalStructureIssue[];
  locked: boolean;
  units: ScopeUnit[];
  /** The Investment whose valuations an LTV constraint may reference; `null`
   * while the Deal has none. */
  valuationOwnerId: string | null;
}

// prettier-ignore
export const REFINANCE_LEDE =
  'A refinance repays loans of one scope at the end of a hold year and funds a replacement loan, sized by the lender constraints you enable. Common Equity receives the net cash, or contributes it when the payoff and costs exceed the new loan.';

// prettier-ignore
export const NO_REFINANCE_MESSAGE =
  'No refinance. Every loan is held to the sale or its own maturity.';

// prettier-ignore
export const REPLACEMENT_TERMS_NOTE =
  'The replacement loan is an ordinary loan in the stack above. Enter its interest rate, amortization, interest-only period, legal maturity and lender fee on its own card; its principal is the gross proceeds this refinance sizes.';

// prettier-ignore
export const DSCR_BASIS_NOTE =
  'Sized on the forward NOI of the year after the refinance and the replacement loan’s actual first-year debt service, interest-only months included.';

// prettier-ignore
export const LTV_BASIS_NOTE =
  'Measured against the selected valuation at the refinance date, for this refinance’s own scope. Nothing else stands in for it.';

// prettier-ignore
export const NO_VALUATION_MESSAGE =
  'No valuation is defined yet. Define one at the refinance date in the Memo workspace’s Valuation panel; fixed and DSCR sizing need none.';

// prettier-ignore
export const REPLACEMENT_FEE_NOTE =
  'Replacement-lender fees are the replacement loan’s own lender fee, entered on its card. Fees paid to a lender being repaid, and third-party costs, are entered here.';

const COST_KIND_LABELS: Readonly<Record<RefinanceCostKind, string>> = {
  retiring_lender_fee: 'Retiring-lender fee',
  third_party_cost: 'Third-party cost',
};

/** The name a refinance is referred to by in messages and controls. */
function eventName(event: CapitalEventForm): string {
  return event.label.trim() === '' ? 'Refinance' : event.label.trim();
}

function positionName(position: PositionForm): string {
  return position.name.trim() === '' ? POSITION_CLASS_LABELS[position.positionClass] : position.name.trim();
}

function unitName(units: ScopeUnit[], unitId: string | null): string {
  return units.find((unit) => unit.unitId === unitId)?.name ?? 'Unit';
}

function scopeName(units: ScopeUnit[], event: CapitalEventForm): string {
  return event.scopeKind === 'investment' ? 'Whole Investment' : unitName(units, event.scopeUnitId);
}

function sameScope(position: PositionForm, event: CapitalEventForm): boolean {
  return event.scopeKind === 'investment'
    ? position.scopeKind === 'investment'
    : position.scopeKind === 'unit' && position.scopeUnitId === event.scopeUnitId;
}

interface RetiringOption {
  key: RetiringKey;
  label: string;
  detail: string;
  /** The rank a replacement of this loan alone succeeds to. */
  priority: string;
}

function retiringOptions(form: CapitalStructureForm, event: CapitalEventForm, units: ScopeUnit[]): RetiringOption[] {
  const options: RetiringOption[] = [];
  if (event.scopeKind === 'unit' && event.scopeUnitId !== null) {
    options.push({
      key: legacyKey(event.scopeUnitId),
      label: units.length > 1 ? `Acquisition loan — ${unitName(units, event.scopeUnitId)}` : 'Acquisition loan',
      detail: 'Senior Debt · the loan this deal is underwritten with',
      priority: '1',
    });
  }
  for (const position of form.positions) {
    if (!isDebt(position.positionClass) || position.fundingKind === 'capital_event' || !sameScope(position, event)) {
      continue;
    }
    options.push({
      key: positionKey(position.positionId),
      label: positionName(position),
      detail: POSITION_CLASS_LABELS[position.positionClass],
      priority: position.priority,
    });
  }
  return options;
}

function replacementOptions(form: CapitalStructureForm, event: CapitalEventForm): PositionForm[] {
  return form.positions.filter(
    (position) =>
      isDebt(position.positionClass) &&
      position.fundingKind === 'capital_event' &&
      sameScope(position, event) &&
      !formEvents(form).some(
        (other) => other.eventId !== event.eventId && other.replacementPositionId === position.positionId,
      ),
  );
}

/** The rank a replacement succeeds to, where the retiring selection says it
 * unambiguously: the acquisition loan's priority 1, or the one authored loan
 * repaid. Otherwise the analyst states it. Selection, never a comparison. */
function successorPriority(event: CapitalEventForm, options: RetiringOption[]): string {
  if (event.retiring.some((key) => key.startsWith('legacy:'))) {
    return '1';
  }
  if (event.retiring.length === 1) {
    return options.find((option) => option.key === event.retiring[0])?.priority ?? '';
  }
  return '';
}

function valuationTiming(choice: ValuationChoice): string {
  const year = eventYearOfMonth(choice.modelMonth);
  return year === null ? `Model Month ${choice.modelMonth}` : endOfYearLabel(year);
}

function TextField({
  id,
  label,
  value,
  onChange,
  disabled,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
}) {
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className="field-input"
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        autoComplete="off"
      />
    </div>
  );
}

function AmountField({
  id,
  label,
  value,
  onChange,
  disabled,
  prefix,
  suffix,
  group = false,
  describedBy,
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

interface EventCardProps {
  ids: string;
  form: CapitalStructureForm;
  event: CapitalEventForm;
  units: ScopeUnit[];
  locked: boolean;
  issues: CapitalStructureIssue[];
  valuations: ReturnType<typeof useValuationChoices>;
  onChange: (form: CapitalStructureForm) => void;
  onRequestRemove: (event: CapitalEventForm, opener: HTMLButtonElement) => void;
  scopesInUse: Set<string>;
}

function scopeKeyOf(kind: 'unit' | 'investment', unitId: string | null): string {
  return kind === 'investment' ? 'investment' : `unit:${unitId ?? ''}`;
}

function EventCard({
  ids,
  form,
  event,
  units,
  locked,
  issues,
  valuations,
  onChange,
  onRequestRemove,
  scopesInUse,
}: EventCardProps) {
  const name = eventName(event);
  const issuesId = `${ids}-issues`;
  const options = retiringOptions(form, event, units);
  const replacements = replacementOptions(form, event);
  const replacement = form.positions.find((position) => position.positionId === event.replacementPositionId);
  const offersScope = units.length > 1;
  const retiringChosen = options.filter((option) => event.retiring.includes(option.key));

  function update(next: CapitalEventForm) {
    onChange({
      ...form,
      events: formEvents(form).map((candidate) => (candidate.eventId === event.eventId ? next : candidate)),
    });
  }

  function set<K extends keyof CapitalEventForm>(key: K, value: CapitalEventForm[K]) {
    update({ ...event, [key]: value });
  }

  function setScope(value: string) {
    const kind: 'unit' | 'investment' = value === 'investment' ? 'investment' : 'unit';
    const unitId = kind === 'unit' ? value : null;
    // A new scope repays different loans and needs its own replacement: the
    // selections that belonged to the old scope are cleared rather than
    // silently carried across (Section 12.4).
    update(
      withRetiring(
        { ...event, scopeKind: kind, scopeUnitId: unitId, replacementPositionId: '' },
        [],
      ),
    );
  }

  function toggleRetiring(key: RetiringKey, checked: boolean) {
    update(
      withRetiring(
        event,
        checked ? [...event.retiring, key] : event.retiring.filter((candidate) => candidate !== key),
      ),
    );
  }

  function addReplacement() {
    const scope = { kind: event.scopeKind, unitId: event.scopeUnitId };
    const loan: PositionForm = {
      ...newPosition(form, 'senior_debt', scope),
      name: `${name} Loan`,
      fundingKind: 'capital_event',
      priority: successorPriority(event, options),
      feeDescription: 'Origination fee',
    };
    onChange({
      ...form,
      positions: [...form.positions, loan],
      events: formEvents(form).map((candidate) =>
        candidate.eventId === event.eventId ? { ...event, replacementPositionId: loan.positionId } : candidate,
      ),
    });
  }

  function updateCost(costId: string, change: Partial<CostLineForm>) {
    set(
      'costs',
      event.costs.map((line) => {
        if (line.costId !== costId) {
          return line;
        }
        const next = { ...line, ...change };
        // A third-party cost is paid to no lender.
        return next.kind === 'third_party_cost' ? { ...next, recipient: '' } : next;
      }),
    );
  }

  function addCost(kind: RefinanceCostKind) {
    set('costs', [...event.costs, newCostLine(event, kind)]);
  }

  function removeCost(costId: string) {
    set(
      'costs',
      event.costs.filter((line) => line.costId !== costId),
    );
  }

  return (
    <fieldset
      className={issues.length > 0 ? 'capital-event capital-position-error' : 'capital-event'}
      aria-describedby={issues.length > 0 ? issuesId : undefined}
    >
      <legend className="capital-position-legend">{name}</legend>

      <div className="capital-position-head">
        <TextField
          id={`${ids}-label`}
          label="Name"
          value={event.label}
          onChange={(value) => set('label', value)}
          disabled={locked}
        />
        {offersScope && (
          <div className="field">
            <label className="field-label" htmlFor={`${ids}-scope`}>
              Scope
            </label>
            <select
              id={`${ids}-scope`}
              className="field-input scenario-select"
              value={event.scopeKind === 'investment' ? 'investment' : (event.scopeUnitId ?? '')}
              onChange={(change) => setScope(change.target.value)}
              disabled={locked}
            >
              {units.map((unit) => (
                <option
                  key={unit.unitId}
                  value={unit.unitId}
                  disabled={
                    scopesInUse.has(scopeKeyOf('unit', unit.unitId)) &&
                    !(event.scopeKind === 'unit' && event.scopeUnitId === unit.unitId)
                  }
                >
                  {unit.name}
                </option>
              ))}
              <option
                value="investment"
                disabled={scopesInUse.has('investment') && event.scopeKind !== 'investment'}
              >
                Whole Investment
              </option>
            </select>
          </div>
        )}
        <div className="field">
          <label className="field-label" htmlFor={`${ids}-year`}>
            Timing
          </label>
          <select
            id={`${ids}-year`}
            className="field-input scenario-select"
            value={event.year}
            onChange={(change) => set('year', change.target.value)}
            disabled={locked}
          >
            <option value="">Choose…</option>
            {EVENT_YEARS.map((year) => (
              <option key={year} value={String(year)}>
                {endOfYearLabel(year)}
              </option>
            ))}
          </select>
        </div>
      </div>

      <fieldset className="capital-event-group">
        <legend className="capital-event-group-title">Loans repaid</legend>
        {options.length === 0 ? (
          <p className="capital-position-note">
            {`${scopeName(units, event)} has no loan this refinance can repay.`}
          </p>
        ) : (
          <ul className="capital-event-checks">
            {options.map((option) => (
              <li key={option.key}>
                <label className="capital-check">
                  <input
                    type="checkbox"
                    checked={event.retiring.includes(option.key)}
                    onChange={(change) => toggleRetiring(option.key, change.target.checked)}
                    disabled={locked}
                  />
                  <span>
                    <span className="capital-event-option-name">{option.label}</span>
                    <span className="capital-event-option-detail">{option.detail}</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
      </fieldset>

      <fieldset className="capital-event-group">
        <legend className="capital-event-group-title">Replacement loan</legend>
        <div className="capital-event-row">
          <div className="field">
            <label className="field-label" htmlFor={`${ids}-replacement`}>
              Funded by this refinance
            </label>
            <select
              id={`${ids}-replacement`}
              className="field-input scenario-select"
              value={event.replacementPositionId}
              onChange={(change) => set('replacementPositionId', change.target.value)}
              disabled={locked || replacements.length === 0}
            >
              <option value="">{replacements.length === 0 ? 'None yet' : 'Choose…'}</option>
              {replacements.map((position) => (
                <option key={position.positionId} value={position.positionId}>
                  {positionName(position)}
                </option>
              ))}
            </select>
          </div>
          {replacement === undefined && (
            <button type="button" className="btn btn-ghost btn-sm capital-event-inline-action" onClick={addReplacement} disabled={locked}>
              Add Replacement Loan
            </button>
          )}
        </div>
        <p className="capital-position-note">{REPLACEMENT_TERMS_NOTE}</p>
        {replacement !== undefined && retiringChosen.length > 0 && (
          <p className="capital-position-note">
            {`It succeeds to the rank of the most senior loan it repays: ${
              successorPriority(event, options) === ''
                ? 'set its priority to that loan’s priority'
                : `priority ${successorPriority(event, options)}`
            }.`}
          </p>
        )}
      </fieldset>

      <fieldset className="capital-event-group">
        <legend className="capital-event-group-title">Sizing constraints</legend>
        <p className="capital-position-note">
          The new loan is the least of every enabled constraint. Enable at least one.
        </p>
        <div className="capital-event-constraint">
          <label className="capital-check">
            <input
              type="checkbox"
              checked={event.fixedCapEnabled}
              onChange={(change) =>
                update({ ...event, fixedCapEnabled: change.target.checked, fixedCap: change.target.checked ? event.fixedCap : '' })
              }
              disabled={locked}
            />
            <span>Fixed maximum proceeds</span>
          </label>
          {event.fixedCapEnabled && (
            <AmountField
              id={`${ids}-fixed-cap`}
              label="Maximum proceeds"
              value={event.fixedCap}
              onChange={(value) => set('fixedCap', value)}
              disabled={locked}
              prefix="$"
              group
            />
          )}
        </div>
        <div className="capital-event-constraint">
          <label className="capital-check">
            <input
              type="checkbox"
              checked={event.ltvEnabled}
              onChange={(change) => update(withLtvEnabled(event, change.target.checked))}
              disabled={locked}
            />
            <span>Maximum LTV</span>
          </label>
          {event.ltvEnabled && (
            <div className="capital-event-constraint-fields">
              <AmountField
                id={`${ids}-max-ltv`}
                label="Maximum LTV"
                value={event.maxLtv}
                onChange={(value) => set('maxLtv', value)}
                disabled={locked}
                suffix="%"
              />
              <div className="field">
                <label className="field-label" htmlFor={`${ids}-valuation`}>
                  Valuation
                </label>
                <select
                  id={`${ids}-valuation`}
                  className="field-input scenario-select"
                  value={event.timepointId}
                  onChange={(change) => set('timepointId', change.target.value)}
                  disabled={locked || valuations.choices.length === 0}
                  aria-describedby={`${ids}-valuation-note`}
                >
                  <option value="">{valuations.choices.length === 0 ? 'None defined' : 'Choose…'}</option>
                  {valuations.choices.map((choice) => (
                    <option key={choice.timepointId} value={choice.timepointId}>
                      {`${choice.label} — ${valuationTiming(choice)}`}
                    </option>
                  ))}
                </select>
              </div>
              <p className="capital-position-note" id={`${ids}-valuation-note`}>
                {valuations.status === 'error'
                  ? 'The valuations could not be loaded. Close and reopen the editor to try again.'
                  : valuations.status === 'loading'
                    ? 'Loading valuations…'
                    : valuations.choices.length === 0
                      ? NO_VALUATION_MESSAGE
                      : LTV_BASIS_NOTE}
              </p>
            </div>
          )}
        </div>
        <div className="capital-event-constraint">
          <label className="capital-check">
            <input
              type="checkbox"
              checked={event.dscrEnabled}
              onChange={(change) =>
                update({ ...event, dscrEnabled: change.target.checked, minDscr: change.target.checked ? event.minDscr : '' })
              }
              disabled={locked}
            />
            <span>Minimum DSCR</span>
          </label>
          {event.dscrEnabled && (
            <div className="capital-event-constraint-fields">
              <AmountField
                id={`${ids}-min-dscr`}
                label="Minimum DSCR"
                value={event.minDscr}
                onChange={(value) => set('minDscr', value)}
                disabled={locked}
                suffix="x"
              />
              <p className="capital-position-note">{DSCR_BASIS_NOTE}</p>
            </div>
          )}
        </div>
      </fieldset>

      <fieldset className="capital-event-group">
        <legend className="capital-event-group-title">Refinance costs</legend>
        <p className="capital-position-note">{REPLACEMENT_FEE_NOTE}</p>
        {event.costs.length > 0 && (
          <ul className="capital-event-costs">
            {event.costs.map((line, index) => {
              const costIds = `${ids}-cost-${index}`;
              return (
                <li key={line.costId} className="capital-event-cost">
                  <div className="field">
                    <label className="field-label" htmlFor={`${costIds}-kind`}>
                      Cost type
                    </label>
                    <select
                      id={`${costIds}-kind`}
                      className="field-input scenario-select"
                      value={line.kind}
                      onChange={(change) => updateCost(line.costId, { kind: change.target.value as RefinanceCostKind })}
                      disabled={locked}
                    >
                      {(Object.keys(COST_KIND_LABELS) as RefinanceCostKind[]).map((kind) => (
                        <option key={kind} value={kind}>
                          {COST_KIND_LABELS[kind]}
                        </option>
                      ))}
                    </select>
                  </div>
                  <AmountField
                    id={`${costIds}-amount`}
                    label="Amount"
                    value={line.amount}
                    onChange={(value) => updateCost(line.costId, { amount: value })}
                    disabled={locked}
                    prefix="$"
                    group
                  />
                  {line.kind === 'retiring_lender_fee' && (
                    <div className="field">
                      <label className="field-label" htmlFor={`${costIds}-recipient`}>
                        Paid to
                      </label>
                      <select
                        id={`${costIds}-recipient`}
                        className="field-input scenario-select"
                        value={line.recipient}
                        onChange={(change) =>
                          updateCost(line.costId, { recipient: change.target.value as RetiringKey | '' })
                        }
                        disabled={locked}
                      >
                        <option value="">{retiringChosen.length === 0 ? 'Select a loan repaid first' : 'Choose…'}</option>
                        {retiringChosen.map((option) => (
                          <option key={option.key} value={option.key}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                  <TextField
                    id={`${costIds}-description`}
                    label="Description"
                    value={line.description}
                    onChange={(value) => updateCost(line.costId, { description: value })}
                    disabled={locked}
                  />
                  <div className="capital-event-cost-actions">
                    <button
                      type="button"
                      className="btn btn-ghost btn-xs"
                      onClick={() => removeCost(line.costId)}
                      disabled={locked}
                      aria-label={`Remove ${COST_KIND_LABELS[line.kind].toLowerCase()} ${line.description.trim() === '' ? '' : line.description.trim()}`.trim()}
                    >
                      Remove
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        <div className="capital-add-row" role="group" aria-label={`Add a cost to ${name}`}>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => addCost('retiring_lender_fee')} disabled={locked}>
            Add Retiring-Lender Fee
          </button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => addCost('third_party_cost')} disabled={locked}>
            Add Third-Party Cost
          </button>
        </div>
      </fieldset>

      {issues.length > 0 && (
        <ul id={issuesId} className="scenario-override-issues" role="alert">
          {issues.map((issue) => (
            <li key={`${issue.code}:${issue.field ?? ''}:${issue.message}`}>{issue.message}</li>
          ))}
        </ul>
      )}

      <div className="capital-position-actions">
        <button
          type="button"
          className="btn btn-ghost btn-xs"
          onClick={(click) => onRequestRemove(event, click.currentTarget)}
          disabled={locked}
          aria-label={`Remove ${name}`}
        >
          Remove Refinance
        </button>
      </div>
    </fieldset>
  );
}

export function CapitalEventEditor({
  prefix,
  form,
  onChange,
  issues,
  locked,
  units,
  valuationOwnerId,
}: CapitalEventEditorProps) {
  const titleId = useId();
  const valuations = useValuationChoices(valuationOwnerId);
  const [pending, setPending] = useState<CapitalEventForm | null>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  const [focusAdd, setFocusAdd] = useState(false);
  const [newScope, setNewScope] = useState<string>('');

  const scopesInUse = new Set(formEvents(form).map((event) => scopeKeyOf(event.scopeKind, event.scopeUnitId)));
  const scopeChoices: { key: string; label: string; kind: 'unit' | 'investment'; unitId: string | null }[] = [
    ...units.map((unit) => ({ key: scopeKeyOf('unit', unit.unitId), label: unit.name, kind: 'unit' as const, unitId: unit.unitId })),
    ...(units.length > 1 ? [{ key: 'investment', label: 'Whole Investment', kind: 'investment' as const, unitId: null }] : []),
  ].filter((choice) => !scopesInUse.has(choice.key));
  const chosenScope = scopeChoices.find((choice) => choice.key === newScope) ?? scopeChoices[0];
  const unstated = unstatedEventChoices(form);

  useEffect(() => {
    if (focusAdd) {
      addButton.current?.focus();
      setFocusAdd(false);
    }
  }, [focusAdd]);

  function add() {
    if (chosenScope === undefined) {
      return;
    }
    onChange({
      ...form,
      events: [...formEvents(form), newCapitalEvent(formEvents(form), { kind: chosenScope.kind, unitId: chosenScope.unitId })],
    });
    setNewScope('');
  }

  function confirmRemove() {
    if (pending === null) {
      return;
    }
    const replacementId = pending.replacementPositionId;
    const remaining = formEvents(form).filter((event) => event.eventId !== pending.eventId);
    // Its replacement loan is funded only by this refinance, so it goes with
    // it; nothing else in the stack changes.
    onChange({
      positions: form.positions.filter((position) => position.positionId !== replacementId),
      events: replacementId === '' ? remaining : withoutPositionReferences(remaining, replacementId),
    });
    setPending(null);
    // The control that opened the confirmation is gone with the refinance, so
    // focus moves to the one that can add it back.
    setFocusAdd(true);
  }

  const replacementName = (event: CapitalEventForm) =>
    form.positions.find((position) => position.positionId === event.replacementPositionId)?.name.trim();

  return (
    <section className="capital-events" aria-labelledby={titleId}>
      <h5 className="capital-events-title" id={titleId}>
        Refinance
      </h5>
      <p className="strategy-domains-lede">{REFINANCE_LEDE}</p>

      {formEvents(form).length === 0 ? (
        <p className="scenario-muted">{NO_REFINANCE_MESSAGE}</p>
      ) : (
        <div className="capital-positions">
          {formEvents(form).map((event, index) => (
            <EventCard
              key={event.eventId}
              ids={`${prefix}-event-${index}`}
              form={form}
              event={event}
              units={units}
              locked={locked}
              issues={issues.filter(
                (issue) =>
                  issue.position_id === event.eventId ||
                  (issue.position_id !== null && issue.position_id === event.replacementPositionId && issue.code !== 'duplicate_priority'),
              )}
              valuations={valuations}
              onChange={onChange}
              onRequestRemove={(target) => setPending(target)}
              scopesInUse={scopesInUse}
            />
          ))}
        </div>
      )}

      {unstated.length > 0 && (
        <div className="capital-unstated" role="status">
          <p className="capital-unstated-title">State these before saving:</p>
          <ul className="capital-unstated-list">
            {unstated.map((entry) => (
              <li key={`${entry.eventId}:${entry.choice}`}>{entry.message}</li>
            ))}
          </ul>
        </div>
      )}

      {scopeChoices.length > 0 && (
        <div className="capital-add-row" role="group" aria-label="Add a refinance">
          {scopeChoices.length > 1 && (
            <div className="field capital-event-new-scope">
              <label className="field-label" htmlFor={`${prefix}-new-refinance-scope`}>
                Refinance scope
              </label>
              <select
                id={`${prefix}-new-refinance-scope`}
                className="field-input scenario-select"
                value={chosenScope?.key ?? ''}
                onChange={(change) => setNewScope(change.target.value)}
                disabled={locked}
              >
                {scopeChoices.map((choice) => (
                  <option key={choice.key} value={choice.key}>
                    {choice.label}
                  </option>
                ))}
              </select>
            </div>
          )}
          <button ref={addButton} type="button" className="btn btn-ghost btn-sm" onClick={add} disabled={locked}>
            Add Refinance
          </button>
        </div>
      )}

      {pending !== null && (
        <ConfirmDialog
          title={`Remove ${eventName(pending)}?`}
          body={
            replacementName(pending)
              ? `The refinance and its replacement loan, ${replacementName(pending)}, are removed from this draft. Every loan it repaid is held to the sale or its own maturity again. Nothing is saved until you save the capital structure.`
              : 'The refinance is removed from this draft. Every loan it repaid is held to the sale or its own maturity again. Nothing is saved until you save the capital structure.'
          }
          confirmLabel="Remove Refinance"
          onConfirm={confirmRemove}
          onCancel={() => setPending(null)}
        />
      )}
    </section>
  );
}
