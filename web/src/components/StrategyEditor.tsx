/**
 * Phase 7 Gate P7.5 -- the Strategy editor.
 *
 * Name and description, then the five decision domains in the backend's order:
 * Acquisition, Financing, Business Plan, Operating Outcome, Disposition. Each
 * domain is a choice between **Inherit Base** and **Strategy-specific**; a
 * strategy-specific domain replaces that whole domain, so every one of its
 * fields is stated. The Business Plan domain has three explicit states --
 * Inherit Base, No Business Plan, Custom -- because an empty replacement plan is
 * a different decision from inheriting Base.
 *
 * **Unit Decisions (P7.6).** A visible Investment's Strategy decides for every
 * Unit: one section per Unit, each naming its Deal, its label and its operating
 * mode, holding that Unit's own five domains -- inherited from that Unit's Base
 * or replaced whole, with the operating-outcome targets of that Unit's mode. A
 * Deal's Strategy has one Unit, the Deal itself, and reads exactly as it did.
 *
 * The analyst never sees a strategy id, a unit id, an enum token or a
 * wire-scale decimal. The Custom Business Plan is the one Business Plan editor
 * (`BusinessPlanEditor`), on the one D6 contract, with its own id prefix.
 * Operating outcomes are always SET, so there is no operation selector; their
 * labels and units are the Scenario target presentation.
 *
 * **Locked while the base is dirty.** An open draft stays on screen, intact,
 * with every control that could change it disabled; Cancel stays available.
 * When the base is clean again the same draft unlocks.
 */

import { Fragment, useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { decisionIdScope, unitDisplayName, unitMeta } from '../investmentCatalog';
import type { DecisionUnit } from '../investmentCatalog';
import { scenarioTargetLabel, scenarioValueFormat } from '../scenarioCatalog';
import {
  BASE_PREFILL_LOADING_MESSAGE,
  BASE_PREFILL_UNAVAILABLE_MESSAGE,
  STRATEGY_DOMAINS,
  STRATEGY_RESOLVES_TO_BASE_MESSAGE,
} from '../strategyCatalog';
import {
  ACQUISITION_FIELDS,
  domainNeedsBase,
  draftHasEconomicContent,
  FINANCING_FIELDS,
  HOLD_PERIOD_LABEL,
} from '../strategyForm';
import type { BusinessPlanChoice, OutcomeRowDraft, StrategyEditorDraft, StrategyUnitDraft } from '../strategyForm';
import type { StrategyDomain, StrategyTargetEntry } from '../strategyTypes';
import type { StrategiesState } from '../useStrategies';
import { BusinessPlanEditor } from './BusinessPlanEditor';
import { CapitalStructureEditor } from './CapitalStructureEditor';
import { NumericInput } from './NumericInput';

export interface StrategyEditorProps {
  /** The id the opening button's `aria-controls` names. */
  id: string;
  state: StrategiesState;
  editor: StrategyEditorDraft;
}

function domainPresentation(domain: StrategyDomain) {
  const found = STRATEGY_DOMAINS.find((entry) => entry.domain === domain);
  if (found === undefined) {
    throw new Error(`Unknown strategy domain ${domain}`);
  }
  return found;
}

interface ModeOption<T extends string> {
  value: T;
  label: string;
}

function ModeChoice<T extends string>({
  name,
  label,
  value,
  options,
  disabled,
  unavailable,
  onChange,
}: {
  name: string;
  label: string;
  value: T;
  options: ModeOption<T>[];
  disabled: boolean;
  /** Options that cannot be chosen yet: they need the saved Base values. */
  unavailable?: ReadonlySet<T>;
  onChange: (value: T) => void;
}) {
  return (
    <div className="strategy-mode" role="radiogroup" aria-label={label}>
      {options.map((option) => (
        <label
          key={option.value}
          className={option.value === value ? 'strategy-mode-option strategy-mode-option-active' : 'strategy-mode-option'}
        >
          <input
            type="radio"
            name={name}
            value={option.value}
            checked={option.value === value}
            disabled={disabled || (unavailable?.has(option.value) ?? false)}
            onChange={() => onChange(option.value)}
          />
          <span>{option.label}</span>
        </label>
      ))}
    </div>
  );
}

const INHERIT_OR_SPECIFIC: ModeOption<'inherit' | 'specific'>[] = [
  { value: 'inherit', label: 'Inherit Base' },
  { value: 'specific', label: 'Strategy-specific' },
];

const SPECIFIC_ONLY: ReadonlySet<'inherit' | 'specific'> = new Set(['specific']);
const CUSTOM_ONLY: ReadonlySet<BusinessPlanChoice> = new Set(['custom']);

const BUSINESS_PLAN_OPTIONS: ModeOption<BusinessPlanChoice>[] = [
  { value: 'inherit', label: 'Inherit Base' },
  { value: 'none', label: 'No Business Plan' },
  { value: 'custom', label: 'Custom Business Plan' },
];

interface DomainSectionProps {
  domain: StrategyDomain;
  /** The element-id prefix of this Unit's section. */
  prefix: string;
  issues: string[];
  choice: ReactNode;
  children: ReactNode;
}

function DomainSection({ domain, prefix, issues, choice, children }: DomainSectionProps) {
  const presentation = domainPresentation(domain);
  const issuesId = `${prefix}-${domain}-issues`;
  return (
    <fieldset
      className={issues.length > 0 ? 'strategy-domain strategy-domain-error' : 'strategy-domain'}
      aria-describedby={issues.length > 0 ? issuesId : undefined}
    >
      <legend className="strategy-domain-legend">{presentation.label}</legend>
      <div className="strategy-domain-head">
        <p className="strategy-domain-replaces">{presentation.replaces}</p>
        {choice}
      </div>
      {children}
      {issues.length > 0 && (
        <ul id={issuesId} className="scenario-override-issues" role="alert">
          {issues.map((issue) => (
            <li key={issue}>{issue}</li>
          ))}
        </ul>
      )}
    </fieldset>
  );
}

function Inherited({ summary }: { summary: string | undefined }) {
  return (
    <p className="strategy-domain-inherit">
      <span className="strategy-domain-inherit-label">Inherits Base</span>
      {summary !== undefined && <span className="strategy-domain-inherit-value">{summary}</span>}
    </p>
  );
}

interface NumberFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  prefix?: string;
  suffix?: string;
  group?: boolean;
}

function NumberField({ id, label, value, onChange, disabled, prefix, suffix, group = false }: NumberFieldProps) {
  // The label names the field alone; its units sit beside the input as affixes.
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

interface OutcomeRowProps {
  unitId: string;
  row: OutcomeRowDraft;
  entries: StrategyTargetEntry[];
  taken: ReadonlySet<string>;
  issues: string[];
  locked: boolean;
  state: StrategiesState;
}

function OutcomeRow({ unitId, row, entries, taken, issues, locked, state }: OutcomeRowProps) {
  const entry = entries.find((candidate) => candidate.target === row.target);
  const label = row.target === '' ? 'this assumption' : scenarioTargetLabel(row.target);
  const offered = entries.filter((candidate) => candidate.target === row.target || !taken.has(candidate.target));
  const isUnoffered = row.target !== '' && entry === undefined;
  const format =
    row.target === ''
      ? null
      : scenarioValueFormat(row.target, 'set', entry === undefined ? undefined : { ...entry, allowed_operations: ['set'] });
  const rowId = `${decisionIdScope(state.investment !== null)}${row.key}`;
  const issuesId = `${rowId}-issues`;
  const hintId = `${rowId}-hint`;
  const describedBy = [format === null ? null : hintId, issues.length > 0 ? issuesId : null]
    .filter((part): part is string => part !== null)
    .join(' ');

  return (
    <Fragment>
      <tr className="scenario-override-row">
        <td className="scenario-override-cell">
          <label className="scenario-override-label" htmlFor={`${rowId}-target`}>
            Assumption
          </label>
          <select
            id={`${rowId}-target`}
            className="field-input scenario-select"
            value={row.target}
            onChange={(event) => state.setOutcomeTarget(unitId, row.key, event.target.value)}
            disabled={locked}
            aria-invalid={issues.length > 0 ? true : undefined}
            aria-describedby={issues.length > 0 ? issuesId : undefined}
          >
            <option value="">Choose assumption…</option>
            {isUnoffered && <option value={row.target}>{scenarioTargetLabel(row.target)}</option>}
            {offered.map((candidate) => (
              <option key={candidate.target} value={candidate.target}>
                {scenarioTargetLabel(candidate.target)}
              </option>
            ))}
          </select>
        </td>
        <td className="scenario-override-cell scenario-override-value">
          <label className="scenario-override-label" htmlFor={`${rowId}-value`}>
            Value<span className="visually-hidden"> for {label}</span>
          </label>
          <div className="field-input-wrap">
            {format?.prefix && <span className="field-affix field-affix-left">{format.prefix}</span>}
            <NumericInput
              id={`${rowId}-value`}
              className="field-input"
              value={row.value}
              onChange={(value) => state.setOutcomeValue(unitId, row.key, value)}
              group={false}
              disabled={locked || format === null}
              aria-invalid={issues.length > 0 ? true : undefined}
              aria-describedby={describedBy === '' ? undefined : describedBy}
              style={{
                paddingLeft: format?.prefix ? '1.4rem' : undefined,
                paddingRight: format?.suffix ? (format.suffix.length > 2 ? '3.9rem' : '1.8rem') : undefined,
              }}
            />
            {format?.suffix && <span className="field-affix field-affix-right">{format.suffix}</span>}
          </div>
          {format !== null && (
            <span className="scenario-override-hint" id={hintId}>
              {format.hint}
            </span>
          )}
        </td>
        <td className="scenario-override-cell scenario-override-remove">
          <button
            type="button"
            className="btn btn-ghost btn-xs"
            onClick={() => state.removeOutcomeRow(unitId, row.key)}
            disabled={locked}
            aria-label={`Remove ${label}`}
          >
            Remove
          </button>
        </td>
      </tr>
      {issues.length > 0 && (
        <tr className="scenario-override-issue-row">
          <td colSpan={3}>
            <ul id={issuesId} className="scenario-override-issues" role="alert">
              {issues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          </td>
        </tr>
      )}
    </Fragment>
  );
}

/** The saved-Base prefill state of one Unit: loading, or unavailable with
 * Retry. Nothing is shown once it is ready. */
function BasePrefillStatus({ state, unitId }: { state: StrategiesState; unitId: string }) {
  const status = state.baseStatusFor(unitId);
  if (status === 'loading') {
    return (
      <p className="scenario-muted" role="status">
        {BASE_PREFILL_LOADING_MESSAGE}
      </p>
    );
  }
  if (status === 'unavailable') {
    return (
      <div className="error-banner scenario-error" role="alert">
        <span>{BASE_PREFILL_UNAVAILABLE_MESSAGE}</span>
        <button type="button" className="btn btn-ghost btn-xs" onClick={() => state.retryBase(unitId)}>
          Retry
        </button>
      </div>
    );
  }
  return null;
}

interface UnitDomainsProps {
  state: StrategiesState;
  unit: StrategyUnitDraft;
  /** The element-id prefix: `strategy` for a Deal, one per Unit otherwise. */
  prefix: string;
  locked: boolean;
}

/** One Unit's five decision domains. */
function UnitDomains({ state, unit, prefix, locked }: UnitDomainsProps) {
  const unitId = unit.unitId;
  const share = state.feedback?.byUnit[unitId];
  const issuesOf = (domain: StrategyDomain) => share?.byDomain[domain] ?? [];
  const base = state.baseFor(unitId);
  const targets = state.targetsFor(unitId);
  const taken = new Set(unit.operatingOutcome.rows.map((row) => row.target).filter((target) => target !== ''));
  const canAddOutcome = state.catalogStatus === 'ready' && targets.some((entry) => !taken.has(entry.target));
  const holdForTiming = unit.disposition.enabled ? unit.disposition.holdPeriod : (base?.holdPeriod ?? '');
  /** A first enable that must copy this Unit's saved Base waits until it is here. */
  const waitsForBase = (domain: StrategyDomain) =>
    state.baseStatusFor(unitId) !== 'ready' && domainNeedsBase(unit, domain);

  return (
    <>
      <DomainSection
        domain="acquisition"
        prefix={prefix}
        issues={issuesOf('acquisition')}
        choice={
          <ModeChoice
            name={`${prefix}-acquisition-mode`}
            label="Acquisition"
            value={unit.acquisition.enabled ? 'specific' : 'inherit'}
            options={INHERIT_OR_SPECIFIC}
            disabled={locked}
            unavailable={waitsForBase('acquisition') ? SPECIFIC_ONLY : undefined}
            onChange={(value) => state.setAcquisitionEnabled(unitId, value === 'specific')}
          />
        }
      >
        {unit.acquisition.enabled ? (
          <div className="strategy-domain-fields">
            {ACQUISITION_FIELDS.map((field) => (
              <NumberField
                key={field.key}
                id={`${prefix}-acquisition-${field.key}`}
                label={field.label}
                value={unit.acquisition[field.key]}
                onChange={(value) => state.setAcquisitionField(unitId, field.key, value)}
                disabled={locked}
                prefix={field.prefix}
                suffix={field.suffix}
                group={field.key === 'purchasePrice'}
              />
            ))}
          </div>
        ) : (
          <Inherited summary={base?.summaries.acquisition} />
        )}
      </DomainSection>

      <DomainSection
        domain="financing"
        prefix={prefix}
        issues={issuesOf('financing')}
        choice={
          <ModeChoice
            name={`${prefix}-financing-mode`}
            label="Financing"
            value={unit.financing.enabled ? 'specific' : 'inherit'}
            options={INHERIT_OR_SPECIFIC}
            disabled={locked}
            unavailable={waitsForBase('financing') ? SPECIFIC_ONLY : undefined}
            onChange={(value) => state.setFinancingEnabled(unitId, value === 'specific')}
          />
        }
      >
        {unit.financing.enabled ? (
          <div className="strategy-domain-fields">
            {FINANCING_FIELDS.map((field) => (
              <NumberField
                key={field.key}
                id={`${prefix}-financing-${field.key}`}
                label={field.label}
                value={unit.financing[field.key]}
                onChange={(value) => state.setFinancingField(unitId, field.key, value)}
                disabled={locked}
                suffix={field.suffix}
              />
            ))}
          </div>
        ) : (
          <Inherited summary={base?.summaries.financing} />
        )}
      </DomainSection>

      <DomainSection
        domain="business_plan"
        prefix={prefix}
        issues={issuesOf('business_plan')}
        choice={
          <ModeChoice
            name={`${prefix}-business-plan-mode`}
            label="Business Plan"
            value={unit.businessPlan.choice}
            options={BUSINESS_PLAN_OPTIONS}
            disabled={locked}
            unavailable={waitsForBase('business_plan') ? CUSTOM_ONLY : undefined}
            onChange={(choice) => state.setBusinessPlanChoice(unitId, choice)}
          />
        }
      >
        {unit.businessPlan.choice === 'inherit' && <Inherited summary={base?.summaries.business_plan} />}
        {unit.businessPlan.choice === 'none' && (
          <p className="strategy-domain-inherit">
            <span className="strategy-domain-inherit-label">No Business Plan</span>
            <span className="strategy-domain-inherit-value">
              This strategy executes no Business Plan: no Project Capital and no Owner Expenses,
              whatever Base holds.
            </span>
          </p>
        )}
        {unit.businessPlan.choice === 'custom' && (
          <>
            <p className="strategy-domain-note">
              A complete replacement plan. It starts as a copy of Base for convenience; once saved it
              is this strategy&apos;s own, and later changes to the Base plan do not reach it.
            </p>
            <BusinessPlanEditor
              idPrefix={`${prefix}-business-plan`}
              embedded
              plan={unit.businessPlan.plan}
              onChange={(plan) => state.setBusinessPlan(unitId, plan)}
              issues={share?.planIssues ?? []}
              holdPeriod={holdForTiming}
              disabled={locked}
            />
          </>
        )}
      </DomainSection>

      <DomainSection
        domain="operating_outcome"
        prefix={prefix}
        issues={issuesOf('operating_outcome')}
        choice={
          <ModeChoice
            name={`${prefix}-operating-outcome-mode`}
            label="Operating Outcome"
            value={unit.operatingOutcome.enabled ? 'specific' : 'inherit'}
            options={INHERIT_OR_SPECIFIC}
            disabled={locked}
            onChange={(value) => state.setOutcomeEnabled(unitId, value === 'specific')}
          />
        }
      >
        {unit.operatingOutcome.enabled ? (
          <div className="scenario-override-block">
            <table className="scenario-override-table strategy-outcome-table">
              <caption className="scenario-override-caption">Operating assumptions, set to</caption>
              <thead>
                <tr>
                  <th scope="col">Assumption</th>
                  <th scope="col">Value</th>
                  <th scope="col">
                    <span className="visually-hidden">Remove</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {unit.operatingOutcome.rows.map((row) => (
                  <OutcomeRow
                    key={row.key}
                    unitId={unitId}
                    row={row}
                    entries={targets}
                    taken={taken}
                    issues={state.feedback?.byRow[row.key] ?? []}
                    locked={locked}
                    state={state}
                  />
                ))}
              </tbody>
            </table>
            {state.catalogStatus !== 'ready' && state.catalogStatus !== 'error' && (
              <p className="scenario-muted" role="status">
                Loading assumptions…
              </p>
            )}
            <div>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => state.addOutcomeRow(unitId)}
                disabled={locked || !canAddOutcome}
              >
                Add Assumption
              </button>
            </div>
          </div>
        ) : (
          <Inherited summary="Every operating assumption is Base's." />
        )}
      </DomainSection>

      <DomainSection
        domain="disposition"
        prefix={prefix}
        issues={issuesOf('disposition')}
        choice={
          <ModeChoice
            name={`${prefix}-disposition-mode`}
            label="Disposition"
            value={unit.disposition.enabled ? 'specific' : 'inherit'}
            options={INHERIT_OR_SPECIFIC}
            disabled={locked}
            unavailable={waitsForBase('disposition') ? SPECIFIC_ONLY : undefined}
            onChange={(value) => state.setDispositionEnabled(unitId, value === 'specific')}
          />
        }
      >
        {unit.disposition.enabled ? (
          <div className="strategy-domain-fields">
            <NumberField
              id={`${prefix}-disposition-holdPeriod`}
              label={HOLD_PERIOD_LABEL}
              value={unit.disposition.holdPeriod}
              onChange={(value) => state.setHoldPeriod(unitId, value)}
              disabled={locked}
              suffix="yrs"
            />
          </div>
        ) : (
          <Inherited summary={base?.summaries.disposition} />
        )}
      </DomainSection>
    </>
  );
}

/** One Unit of a multi-unit Strategy: its identity, its prefill state and its
 * five domains. */
function UnitSection({
  state,
  unit,
  position,
  locked,
}: {
  state: StrategiesState;
  unit: StrategyUnitDraft;
  position: number;
  locked: boolean;
}) {
  const known: DecisionUnit | undefined = state.units.find((candidate) => candidate.unitId === unit.unitId);
  const ids = decisionIdScope(state.investment !== null);
  const headingId = `${ids}strategy-unit-${position}-title`;
  return (
    <section className="strategy-unit" aria-labelledby={headingId}>
      <div className="strategy-unit-head">
        <h5 id={headingId} className="strategy-unit-name">
          {known === undefined ? unit.unitId : unitDisplayName(known)}
        </h5>
        {known !== undefined && <span className="strategy-unit-meta">{unitMeta(known)}</span>}
      </div>
      <BasePrefillStatus state={state} unitId={unit.unitId} />
      <UnitDomains state={state} unit={unit} prefix={`${ids}strategy-u${position}`} locked={locked} />
    </section>
  );
}

export function StrategyEditor({ id, state, editor }: StrategyEditorProps) {
  const nameInput = useRef<HTMLInputElement>(null);
  const feedback = state.feedback;
  const locked = !state.canEdit;
  const isMultiUnit = state.investment !== null;
  const ids = decisionIdScope(isMultiUnit);
  const onlyUnit = editor.units[0];

  useEffect(() => {
    nameInput.current?.focus();
  }, []);

  return (
    <section id={id} className="scenario-editor strategy-editor" aria-labelledby={`${ids}strategy-editor-title`}>
      <h4 id={`${ids}strategy-editor-title`} className="scenario-editor-title">
        {editor.strategyId === null ? 'New Strategy' : 'Edit Strategy'}
      </h4>

      {feedback !== null && (
        <div className="error-banner scenario-editor-feedback" role="alert">
          <p className="scenario-editor-feedback-message">{feedback.message}</p>
          {feedback.general.length > 0 && (
            <ul className="scenario-editor-feedback-list">
              {feedback.general.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {state.catalogStatus === 'error' && (
        <div className="error-banner scenario-error" role="alert">
          <span>{state.catalogError}</span>
          <button type="button" className="btn btn-ghost btn-xs" onClick={state.retryCatalog}>
            Retry
          </button>
        </div>
      )}

      <div className="scenario-editor-fields">
        <label className="field" htmlFor={`${ids}strategy-editor-name`}>
          <span className="field-label">Strategy Name</span>
          <input
            ref={nameInput}
            id={`${ids}strategy-editor-name`}
            className="field-input"
            type="text"
            value={editor.name}
            onChange={(event) => state.setName(event.target.value)}
            disabled={locked}
            autoComplete="off"
          />
        </label>
        <label className="field" htmlFor={`${ids}strategy-editor-description`}>
          <span className="field-label">Description (optional)</span>
          <input
            id={`${ids}strategy-editor-description`}
            className="field-input"
            type="text"
            value={editor.description}
            onChange={(event) => state.setDescription(event.target.value)}
            disabled={locked}
            autoComplete="off"
          />
        </label>
      </div>

      <p className="strategy-domains-lede">
        {isMultiUnit
          ? 'Each Unit’s decision domains inherit that Unit’s own Base unless you make them strategy-specific. A strategy-specific domain replaces that whole domain for that Unit; later changes to Base do not reach it.'
          : 'Each decision domain inherits Base unless you make it strategy-specific. A strategy-specific domain replaces that whole domain; later changes to Base do not reach it.'}
      </p>
      {!draftHasEconomicContent(editor) && (
        <p className="strategy-resolves-to-base" role="status">
          {STRATEGY_RESOLVES_TO_BASE_MESSAGE}
        </p>
      )}

      {isMultiUnit ? (
        <div className="strategy-units" role="group" aria-labelledby={`${ids}strategy-units-title`}>
          <h5 id={`${ids}strategy-units-title`} className="strategy-units-title">
            Unit Decisions
          </h5>
          {editor.units.map((unit, position) => (
            <UnitSection key={unit.unitId} state={state} unit={unit} position={position} locked={locked} />
          ))}
        </div>
      ) : (
        onlyUnit !== undefined && (
          <>
            <BasePrefillStatus state={state} unitId={onlyUnit.unitId} />
            <UnitDomains state={state} unit={onlyUnit} prefix={`${ids}strategy`} locked={locked} />
          </>
        )
      )}

      {/* The whole-transaction domain, stated once rather than per Unit: its
        * positions carry their own scope, so there is nothing to address by
        * unit_id. Inherit Base and Strategy-specific are different wire bodies,
        * and a strategy-specific structure holding no position is the third,
        * explicit decision -- use no structured capital at all. */}
      <fieldset className="strategy-domain strategy-root-domain">
        <legend className="strategy-domain-legend">
          {domainPresentation('capital_structure').label}
        </legend>
        <div className="strategy-domain-head">
          <p className="strategy-domain-replaces">
            {domainPresentation('capital_structure').replaces}
          </p>
          <ModeChoice
            name={`${ids}strategy-capital-structure-mode`}
            label="Capital Structure"
            value={editor.capitalStructure.choice}
            options={INHERIT_OR_SPECIFIC}
            disabled={locked}
            onChange={(value) => state.setCapitalStructureChoice(value)}
          />
        </div>
        {editor.capitalStructure.choice === 'inherit' ? (
          <Inherited summary="Every position is Base’s." />
        ) : (
          <>
            <p className="strategy-domain-note">
              A complete replacement structure. It starts as a copy of Base for convenience; once
              saved it is this strategy&apos;s own, and later changes to Base do not reach it. A
              structure with no position is a real choice: this strategy uses no structured capital.
            </p>
            <CapitalStructureEditor
              id={`${ids}strategy-capital-structure`}
              prefix={`${ids}strategy-capital`}
              form={editor.capitalStructure.form}
              onChange={(form) => state.setCapitalStructure(form)}
              issues={[]}
              locked={locked}
              lockedReason={null}
              units={state.units.map((unit) => ({
                unitId: unit.unitId,
                name: unitDisplayName(unit),
              }))}
              embedded
            />
          </>
        )}
      </fieldset>

      <div className="scenario-editor-actions">
        <button type="button" className="btn btn-ghost btn-sm" onClick={state.cancelEdit} disabled={state.isSaving}>
          Cancel
        </button>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={() => void state.saveEditor()}
          disabled={state.isSaving || locked}
        >
          {state.isSaving ? 'Saving…' : 'Save Strategy'}
        </button>
      </div>
    </section>
  );
}
