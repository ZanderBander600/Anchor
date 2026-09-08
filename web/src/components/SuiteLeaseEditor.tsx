/**
 * D5.5B -- the advanced editor for one rent-roll row.
 *
 * **One drawer, four sections**, rather than a modal per concern. Entering a
 * 30-suite property through five modals a suite is sixty open/save cycles for
 * one building; the drawer opens once and holds everything the grid could not
 * fit, with the row still visible behind it.
 *
 * Which sections appear follows the suite's actual state, because the contract
 * does: an occupied suite must carry no initial-vacancy treatment
 * (`INITIAL_VACANCY_ON_OCCUPIED_SUITE`) and a vacant one must carry exactly one
 * (`MISSING_INITIAL_VACANCY_TREATMENT`). The editor shows the section the suite
 * can legally have, and never both.
 *
 * It computes nothing. Every control writes a string the analyst typed.
 */

import type { ChangeEvent, ReactNode } from 'react';
import { AssumptionFieldGrid } from './AssumptionFieldGrid';
import {
  ESCALATION_BASIS_OPTIONS,
  INITIAL_VACANCY_STRATEGY_OPTIONS,
  LEASE_LEVEL_MARKET_FIELD_GROUPS,
  LEASE_TYPE_OPTIONS,
  LEASING_COMMISSION_METHOD_OPTIONS,
  MARKET_LEASING_EXPENSE_STOP_FIELDS,
  RECOVERY_BASIS_OPTIONS,
  isRowOccupied,
  wireFieldName,
} from '../leaseLevelConvert';
import type { SelectOption } from '../leaseLevelConvert';
import type { FieldSection } from '../underwrite';
import type {
  InitialVacancyFormValues,
  LeaseFormValues,
  MarketLeasingFormValues,
  SuiteRowFormValues,
} from '../leaseLevelTypes';
import type { RowIssues } from '../leaseLevelIssues';

export interface SuiteLeaseEditorProps {
  row: SuiteRowFormValues;
  issues: RowIssues | undefined;
  disabled: boolean;
  onClose: () => void;
  onSuiteFieldChange: (
    rowId: string,
    key: 'suiteId' | 'suiteAreaSf' | 'suiteLabel' | 'marketRentPsf',
    value: string,
  ) => void;
  onLeaseFieldChange: (
    rowId: string,
    key: keyof Omit<LeaseFormValues, 'origin'>,
    value: string,
  ) => void;
  onVacancyFieldChange: (
    rowId: string,
    key: keyof InitialVacancyFormValues,
    value: string,
  ) => void;
  onOverrideFieldChange: (
    rowId: string,
    key: keyof MarketLeasingFormValues,
    value: string,
  ) => void;
  onToggleOverride: (rowId: string) => void;
  onUseSuiteArea: (rowId: string) => void;
}

/** The ids describing one control: its hint, its error, or both. */
function describedBy(id: string, hint?: string, error?: string): string | undefined {
  const parts = [hint ? `${id}-hint` : null, error ? `${id}-error` : null].filter(
    (part): part is string => part !== null,
  );
  return parts.length === 0 ? undefined : parts.join(' ');
}

function messageFor(issues: RowIssues | undefined, field: string): string | undefined {
  return issues?.fields.get(field)?.message;
}

interface TextFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  error?: string;
  type?: 'text' | 'number' | 'date';
  hint?: string;
  placeholder?: string;
  after?: ReactNode;
}

function TextField({
  id,
  label,
  value,
  onChange,
  disabled,
  error,
  type = 'text',
  hint,
  placeholder,
  after,
}: TextFieldProps) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <div className="field-with-action">
        <input
          id={id}
          className="field-input"
          type={type}
          inputMode={type === 'number' ? 'decimal' : undefined}
          step={type === 'number' ? 'any' : undefined}
          value={value}
          disabled={disabled}
          placeholder={placeholder}
          /* The hint and the error are *descriptions*, not part of the name.
           * Left to the wrapping `<label>` they would be absorbed into it, and
           * this field would answer to "Expense Stop Annual $/SF. A contract
           * term Anchor never infers." instead of to "Expense Stop". */
          aria-label={label}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy(id, hint, error)}
          onChange={(event: ChangeEvent<HTMLInputElement>) => onChange(event.target.value)}
        />
        {after}
      </div>
      {hint && (
        <span className="field-hint field-hint-inline" id={`${id}-hint`}>
          {hint}
        </span>
      )}
      {error && (
        <span className="field-error" id={`${id}-error`} role="alert">
          {error}
        </span>
      )}
    </label>
  );
}

interface SelectFieldProps {
  id: string;
  label: string;
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  disabled: boolean;
  error?: string;
  nullable?: boolean;
  hint?: string;
}

function SelectField({
  id,
  label,
  value,
  options,
  onChange,
  disabled,
  error,
  nullable,
  hint,
}: SelectFieldProps) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <select
        id={id}
        className="field-input"
        value={value}
        disabled={disabled}
        aria-label={label}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, hint, error)}
        onChange={(event: ChangeEvent<HTMLSelectElement>) => onChange(event.target.value)}
      >
        <option value="">{nullable ? 'None' : 'Select…'}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {hint && (
        <span className="field-hint field-hint-inline" id={`${id}-hint`}>
          {hint}
        </span>
      )}
      {error && (
        <span className="field-error" id={`${id}-error`} role="alert">
          {error}
        </span>
      )}
    </label>
  );
}

export function SuiteLeaseEditor({
  row,
  issues,
  disabled,
  onClose,
  onSuiteFieldChange,
  onLeaseFieldChange,
  onVacancyFieldChange,
  onOverrideFieldChange,
  onToggleOverride,
  onUseSuiteArea,
}: SuiteLeaseEditorProps) {
  const occupied = isRowOccupied(row);
  const name = row.suiteId.trim() === '' ? 'the new suite' : `Suite ${row.suiteId}`;
  const lease = row.lease;

  const overrideSections: FieldSection[] = LEASE_LEVEL_MARKET_FIELD_GROUPS.map((group) => ({
    view: null,
    title: group.title,
    fields: group.fields.map((field) => ({
      id: `override-${row.rowId}-${field.key}`,
      label: field.label,
      prefix: field.prefix,
      suffix: field.suffix,
      value: row.marketLeasingOverride[field.key],
      onChange: (value: string) => onOverrideFieldChange(row.rowId, field.key, value),
      error: messageFor(issues, `market_leasing_override.${wireFieldName(field.key)}`),
    })),
  }));

  const overrideStopSection: FieldSection[] = [
    {
      view: null,
      title: 'Expense Stops',
      fields: MARKET_LEASING_EXPENSE_STOP_FIELDS.map((field) => ({
        id: `override-${row.rowId}-${field.key}`,
        label: field.label,
        prefix: field.prefix,
        suffix: field.suffix,
        value: row.marketLeasingOverride[field.key],
        onChange: (value: string) => onOverrideFieldChange(row.rowId, field.key, value),
        error: messageFor(issues, `market_leasing_override.${wireFieldName(field.key)}`),
      })),
    },
  ];

  return (
    <aside
      className="suite-editor"
      role="dialog"
      aria-modal="false"
      aria-label={`Details for ${name}`}
    >
      <header className="suite-editor-head">
        <div>
          <h3 className="suite-editor-title">{name}</h3>
          <p className="suite-editor-subtitle">{occupied ? 'Occupied' : 'Vacant'}</p>
        </div>
        <button type="button" className="btn btn-ghost btn-xs" onClick={onClose}>
          Close
        </button>
      </header>

      {issues && issues.rowLevel.length > 0 && (
        <div className="error-banner" role="alert">
          <ul className="lease-level-issue-list">
            {issues.rowLevel.map((issue) => (
              <li key={`${issue.code}-${issue.path}`}>{issue.message}</li>
            ))}
          </ul>
        </div>
      )}

      <section className="suite-editor-section">
        <h4 className="suite-editor-section-title">Suite</h4>
        <div className="assumption-field-grid">
          <TextField
            id={`editor-suite-id-${row.rowId}`}
            label="Suite"
            value={row.suiteId}
            onChange={(next) => onSuiteFieldChange(row.rowId, 'suiteId', next)}
            disabled={disabled}
            error={messageFor(issues, 'suite_id')}
          />
          <TextField
            id={`editor-suite-area-${row.rowId}`}
            label="Suite Area"
            value={row.suiteAreaSf}
            onChange={(next) => onSuiteFieldChange(row.rowId, 'suiteAreaSf', next)}
            disabled={disabled}
            type="number"
            error={messageFor(issues, 'suite_area_sf')}
          />
          <TextField
            id={`editor-suite-label-${row.rowId}`}
            label="Suite Label"
            value={row.suiteLabel}
            onChange={(next) => onSuiteFieldChange(row.rowId, 'suiteLabel', next)}
            disabled={disabled}
            hint="Optional. Left blank, the suite is unlabelled."
          />
          <TextField
            id={`editor-suite-market-rent-${row.rowId}`}
            label="Suite Market Rent"
            value={row.marketRentPsf}
            onChange={(next) => onSuiteFieldChange(row.rowId, 'marketRentPsf', next)}
            disabled={disabled}
            type="number"
            placeholder="Property default"
            hint="Overrides the rent level alone. Blank inherits the property default."
            error={messageFor(issues, 'market_rent_psf')}
          />
        </div>
      </section>

      {lease !== null && (
        <section className="suite-editor-section">
          <h4 className="suite-editor-section-title">Lease</h4>
          <div className="assumption-field-grid">
            <TextField
              id={`editor-lease-id-${row.rowId}`}
              label="Lease ID"
              value={lease.leaseId}
              onChange={(next) => onLeaseFieldChange(row.rowId, 'leaseId', next)}
              disabled={disabled}
              error={messageFor(issues, 'lease_id')}
            />
            <TextField
              id={`editor-lease-tenant-${row.rowId}`}
              label="Tenant"
              value={lease.tenantName}
              onChange={(next) => onLeaseFieldChange(row.rowId, 'tenantName', next)}
              disabled={disabled}
              error={messageFor(issues, 'tenant_name')}
            />
            <TextField
              id={`editor-lease-area-${row.rowId}`}
              label="Leased Area"
              value={lease.leasedAreaSf}
              onChange={(next) => onLeaseFieldChange(row.rowId, 'leasedAreaSf', next)}
              disabled={disabled}
              type="number"
              error={messageFor(issues, 'leased_area_sf')}
              // An explicit action, never an automatic mirror. The backend
              // requires the two to be equal today, but copying silently would
              // hide a rent roll that genuinely disagrees with itself -- and
              // would then have to decide what to do when the suite area later
              // changes.
              after={
                <button
                  type="button"
                  className="btn btn-ghost btn-xs field-action"
                  disabled={disabled}
                  onClick={() => onUseSuiteArea(row.rowId)}
                >
                  Use Suite Area
                </button>
              }
            />
            <TextField
              id={`editor-lease-commencement-${row.rowId}`}
              label="Rent Commencement"
              value={lease.rentCommencementDate}
              onChange={(next) => onLeaseFieldChange(row.rowId, 'rentCommencementDate', next)}
              disabled={disabled}
              type="date"
              error={messageFor(issues, 'rent_commencement_date')}
            />
            <TextField
              id={`editor-lease-expiration-${row.rowId}`}
              label="Lease Expiration"
              value={lease.leaseExpirationDate}
              onChange={(next) => onLeaseFieldChange(row.rowId, 'leaseExpirationDate', next)}
              disabled={disabled}
              type="date"
              error={messageFor(issues, 'lease_expiration_date')}
            />
            <TextField
              id={`editor-lease-start-${row.rowId}`}
              label="Lease Start (possession)"
              value={lease.leaseStartDate}
              onChange={(next) => onLeaseFieldChange(row.rowId, 'leaseStartDate', next)}
              disabled={disabled}
              type="date"
              hint="Optional. Informational only; it enters no calculation."
              error={messageFor(issues, 'lease_start_date')}
            />
            <TextField
              id={`editor-lease-rent-${row.rowId}`}
              label="Base Rent"
              value={lease.baseRentPsf}
              onChange={(next) => onLeaseFieldChange(row.rowId, 'baseRentPsf', next)}
              disabled={disabled}
              type="number"
              hint="Annual $/SF as of rent commencement."
              error={messageFor(issues, 'base_rent_psf')}
            />
            <TextField
              id={`editor-lease-escalation-${row.rowId}`}
              label="Escalation"
              value={lease.escalationPct}
              onChange={(next) => onLeaseFieldChange(row.rowId, 'escalationPct', next)}
              disabled={disabled}
              type="number"
              error={messageFor(issues, 'escalation_pct')}
            />
            <SelectField
              id={`editor-lease-escalation-basis-${row.rowId}`}
              label="Escalation Basis"
              value={lease.escalationBasis}
              options={ESCALATION_BASIS_OPTIONS}
              onChange={(next) => onLeaseFieldChange(row.rowId, 'escalationBasis', next)}
              disabled={disabled}
              error={messageFor(issues, 'escalation_basis')}
            />
            <SelectField
              id={`editor-lease-type-${row.rowId}`}
              label="Lease Type"
              value={lease.leaseType}
              options={LEASE_TYPE_OPTIONS}
              onChange={(next) => onLeaseFieldChange(row.rowId, 'leaseType', next)}
              disabled={disabled}
              error={messageFor(issues, 'lease_type')}
            />
            {/* Recovery terms belong to Modified Gross alone: a stop on an NNN
                or Gross lease is a validation error, because a stop implies
                Modified Gross. The controls appear only where the contract can
                carry them -- but a value already stored is never cleared just
                because the fields are hidden, so switching type twice does not
                silently discard a contractual stop. */}
            {lease.leaseType === 'modified_gross' && (
              <>
                <SelectField
                  id={`editor-lease-recovery-${row.rowId}`}
                  label="Recovery Basis"
                  value={lease.recoveryBasis}
                  options={RECOVERY_BASIS_OPTIONS}
                  onChange={(next) => onLeaseFieldChange(row.rowId, 'recoveryBasis', next)}
                  disabled={disabled}
                  nullable
                  error={messageFor(issues, 'recovery_basis')}
                />
                <TextField
                  id={`editor-lease-stop-${row.rowId}`}
                  label="Expense Stop"
                  value={lease.expenseStopPsf}
                  onChange={(next) => onLeaseFieldChange(row.rowId, 'expenseStopPsf', next)}
                  disabled={disabled}
                  type="number"
                  hint="Annual $/SF. A contract term Anchor never infers."
                  error={messageFor(issues, 'expense_stop_psf')}
                />
              </>
            )}
          </div>
        </section>
      )}

      {!occupied && (
        <section className="suite-editor-section">
          <h4 className="suite-editor-section-title">Initial Vacancy</h4>
          <p className="field-hint">
            Vacant space is underwritten explicitly. Anchor does not assume it
            stays empty, and does not assume it lets.
          </p>
          <div className="assumption-field-grid">
            <SelectField
              id={`editor-vacancy-strategy-${row.rowId}`}
              label="Initial Vacancy Strategy"
              value={row.initialVacancy.strategy}
              options={INITIAL_VACANCY_STRATEGY_OPTIONS}
              onChange={(next) => onVacancyFieldChange(row.rowId, 'strategy', next)}
              disabled={disabled}
              error={
                messageFor(issues, 'initial_vacancy') ??
                messageFor(issues, 'initial_vacancy.strategy')
              }
            />
            {/* Only Market Lease-Up can carry a lease-up period; Hold Vacant
                must not. The value the analyst typed is kept in local state
                either way, so toggling back does not lose it, and the
                conversion drops it on the way out. */}
            {row.initialVacancy.strategy === 'market_lease_up' && (
              <TextField
                id={`editor-vacancy-months-${row.rowId}`}
                label="Initial Lease-Up Months"
                value={row.initialVacancy.initialLeaseUpMonths}
                onChange={(next) =>
                  onVacancyFieldChange(row.rowId, 'initialLeaseUpMonths', next)
                }
                disabled={disabled}
                type="number"
                hint="How long space already empty takes to fill. Not the same as new-tenant downtime."
                error={messageFor(issues, 'initial_vacancy.initial_lease_up_months')}
              />
            )}
          </div>
        </section>
      )}

      <section className="suite-editor-section">
        <h4 className="suite-editor-section-title">Market Leasing</h4>
        <div className="suite-editor-override-toggle">
          <label className="field-checkbox">
            <input
              id={`editor-override-enabled-${row.rowId}`}
              type="checkbox"
              checked={row.marketLeasingOverrideEnabled}
              disabled={disabled}
              onChange={() => onToggleOverride(row.rowId)}
            />
            <span>Use full suite leasing assumptions</span>
          </label>
          <p className="field-hint">
            {row.marketLeasingOverrideEnabled
              ? 'Full suite leasing assumptions take precedence while enabled, including over the Suite Market Rent above. That value is kept and applies again if you turn this off.'
              : 'Using the property defaults. A full override replaces the entire record — it is all-or-nothing, never a per-field merge.'}
          </p>
        </div>

        {row.marketLeasingOverrideEnabled && (
          <>
            <AssumptionFieldGrid sections={overrideSections} disabled={disabled} />
            <div className="assumption-sections">
              <section className="assumption-section">
                <h3 className="assumption-section-title">Lease Structure &amp; Recoveries</h3>
                <div className="assumption-field-grid">
                  <SelectField
                    id={`override-${row.rowId}-renewalLeaseType`}
                    label="Renewal Lease Type"
                    value={row.marketLeasingOverride.renewalLeaseType}
                    options={LEASE_TYPE_OPTIONS}
                    onChange={(next) =>
                      onOverrideFieldChange(row.rowId, 'renewalLeaseType', next)
                    }
                    disabled={disabled}
                    error={messageFor(issues, 'market_leasing_override.renewal_lease_type')}
                  />
                  <SelectField
                    id={`override-${row.rowId}-renewalRecoveryBasis`}
                    label="Renewal Recovery Basis"
                    value={row.marketLeasingOverride.renewalRecoveryBasis}
                    options={RECOVERY_BASIS_OPTIONS}
                    onChange={(next) =>
                      onOverrideFieldChange(row.rowId, 'renewalRecoveryBasis', next)
                    }
                    disabled={disabled}
                    nullable
                    error={messageFor(issues, 'market_leasing_override.renewal_recovery_basis')}
                  />
                  <SelectField
                    id={`override-${row.rowId}-newLeaseType`}
                    label="New Lease Type"
                    value={row.marketLeasingOverride.newLeaseType}
                    options={LEASE_TYPE_OPTIONS}
                    onChange={(next) => onOverrideFieldChange(row.rowId, 'newLeaseType', next)}
                    disabled={disabled}
                    error={messageFor(issues, 'market_leasing_override.new_lease_type')}
                  />
                  <SelectField
                    id={`override-${row.rowId}-newRecoveryBasis`}
                    label="New Recovery Basis"
                    value={row.marketLeasingOverride.newRecoveryBasis}
                    options={RECOVERY_BASIS_OPTIONS}
                    onChange={(next) =>
                      onOverrideFieldChange(row.rowId, 'newRecoveryBasis', next)
                    }
                    disabled={disabled}
                    nullable
                    error={messageFor(issues, 'market_leasing_override.new_recovery_basis')}
                  />
                  <SelectField
                    id={`override-${row.rowId}-leasingCommissionMethod`}
                    label="Leasing Commission Method"
                    value={row.marketLeasingOverride.leasingCommissionMethod}
                    options={LEASING_COMMISSION_METHOD_OPTIONS}
                    onChange={(next) =>
                      onOverrideFieldChange(row.rowId, 'leasingCommissionMethod', next)
                    }
                    disabled={disabled}
                    error={messageFor(
                      issues,
                      'market_leasing_override.leasing_commission_method',
                    )}
                  />
                </div>
              </section>
            </div>
            <AssumptionFieldGrid sections={overrideStopSection} disabled={disabled} />
          </>
        )}
      </section>
    </aside>
  );
}
