/**
 * D5.5A -- the Lease-Level underwriting workspace.
 *
 * Its own component rather than a third branch inside `UnderwriteWorkspace`.
 * Quick and Detailed are columns of scalar assumptions; Lease-Level is
 * forty-odd scalars *plus* a rent roll, and D5.5B adds two editable grids to
 * it. Routing it through the shared workspace would mean bending that
 * component around a shape it was not built for, and would put Lease-Level's
 * future editors inside Quick's and Detailed's blast radius. It composes the
 * same primitives throughout -- `AssumptionFieldGrid`, `SubNav`,
 * `StrategyStrip` -- so nothing here is a new visual language.
 *
 * **Scope.** Scalar entry only. The rent roll is *held*, described, and passed
 * through untouched; D5.5B supplies the Suite and Lease editors. No results are
 * rendered: D5.6 owns that, and this component deliberately never calls
 * `resultsViewsFor`, which still refuses Lease-Level.
 *
 * **It computes nothing.** Every value shown is either a string the analyst
 * typed or a count of rows they loaded. No rent, escalation, recovery, area
 * total or period conversion happens here (G-M7).
 */

import type { ChangeEvent, ReactNode } from 'react';
import { AssumptionFieldGrid } from './AssumptionFieldGrid';
import { StrategyStrip } from './StrategyStrip';
import { SubNav } from './SubNav';
import {
  LEASE_LEVEL_MARKET_FIELD_GROUPS,
  LEASE_LEVEL_OPERATING_FIELD_GROUPS,
  LEASE_LEVEL_PROPERTY_FIELD_GROUPS,
  LEASE_TYPE_OPTIONS,
  LEASING_COMMISSION_METHOD_OPTIONS,
  MARKET_LEASING_EXPENSE_STOP_FIELDS,
  RECOVERY_BASIS_OPTIONS,
  TERMS_WIRE_IDS,
  wireFieldName,
} from '../leaseLevelConvert';
import type { LeaseLevelFieldConfig, SelectOption } from '../leaseLevelConvert';
import { TERMS_FIELD_GROUPS } from '../convert';
import type { FieldSection } from '../underwrite';
import type {
  LeaseLevelFormValues,
  LeaseLevelIssue,
  LeaseLevelOperatingFormValues,
  LeaseLevelPropertyFormValues,
  MarketLeasingFormValues,
} from '../leaseLevelTypes';
import type { AcquisitionTermsFormValues, ValidationIssue } from '../types';

/**
 * The workspace's sections.
 *
 * Deliberately not the five Underwrite tabs. Lease-Level has no Results view
 * until D5.6, and its operating content is three distinct concerns each large
 * enough to earn a section. Acquisition and Debt share one section because
 * Lease-Level adds nothing to either, and splitting eleven terms across two
 * near-empty tabs would be navigation for its own sake.
 */
export type LeaseLevelSectionId =
  | 'acquisition'
  | 'property'
  | 'operating'
  | 'market'
  | 'rent-roll';

/* Not exported: a component module that also exports values loses fast
 * refresh, and nothing outside this file needs the list. */
const LEASE_LEVEL_SECTIONS: { id: LeaseLevelSectionId; label: string }[] = [
  { id: 'acquisition', label: 'Acquisition & Debt' },
  { id: 'property', label: 'Property' },
  { id: 'operating', label: 'Operating' },
  { id: 'market', label: 'Market Leasing' },
  { id: 'rent-roll', label: 'Rent Roll' },
];

export interface LeaseLevelWorkspaceProps {
  values: LeaseLevelFormValues;
  activeSection: LeaseLevelSectionId;
  onSectionChange: (section: LeaseLevelSectionId) => void;
  onTermsFieldChange: (key: keyof AcquisitionTermsFormValues, value: string) => void;
  onPropertyFieldChange: (key: keyof LeaseLevelPropertyFormValues, value: string) => void;
  onOperatingFieldChange: (key: keyof LeaseLevelOperatingFormValues, value: string) => void;
  onMarketFieldChange: (key: keyof MarketLeasingFormValues, value: string) => void;
  dealContext: string;
  onDealContextChange: (value: string) => void;
  /** True while an analysis or save is in flight; disables every input, exactly
   * as the shared workspace does. */
  isSubmitting: boolean;
  /** Lease-Level issues from the last refused submission, each carrying its
   * `path`. */
  leaseIssues: LeaseLevelIssue[];
  /** `terms` issues from the same refusal, in the shared Quick/Detailed shape. */
  termsIssues: ValidationIssue[];
  /** The whole-request message, shown when nothing more specific can be
   * anchored -- a transport failure, or an issue whose `path` names something
   * this gate does not yet render. */
  error: string | null;
}

// ---------------------------------------------------------------------------
// Issue anchoring.
//
// The backend's `path` names the field, so anchoring is a lookup and never a
// guess. A path this gate cannot place is not discarded: it falls through to
// the banner list. An error the analyst cannot see anywhere is worse than one
// shown in a slightly clumsy place, because it turns a refused analysis into an
// unexplained one.
// ---------------------------------------------------------------------------

/** The three scalar input objects, by their wire key. */
const SCALAR_OBJECTS = ['property_inputs', 'operating_inputs', 'market_leasing'] as const;

type ScalarObject = (typeof SCALAR_OBJECTS)[number];

function messageFor(
  issues: LeaseLevelIssue[],
  object: ScalarObject,
  field: string,
): string | undefined {
  return issues.find((issue) => issue.path === `${object}.${field}`)?.message;
}

function termsMessageFor(issues: ValidationIssue[], wireId: string): string | undefined {
  return issues.find((issue) => issue.field_id === wireId)?.message;
}

/**
 * Every path this workspace has a field for.
 *
 * Derived from the form values themselves -- the keys present are exactly the
 * fields rendered -- so it cannot claim a field that is not on screen, and a
 * field added to a contract joins it automatically.
 *
 * The distinction matters more than it looks. Asking only whether a path
 * *starts with* a known object would call `market_leasing.market_rent` anchored,
 * find no field to hang it on, and drop it: an issue silently lost inside an
 * object the workspace does render. Membership is exact, and anything not in the
 * set falls through to the banner -- every `suites[...]` and `leases[...]` path
 * included, which D5.5B will anchor to its row.
 */
function anchorablePaths(values: LeaseLevelFormValues): Set<string> {
  const paths = new Set<string>();
  const groups: [ScalarObject, object][] = [
    ['property_inputs', values.property],
    ['operating_inputs', values.operating],
    ['market_leasing', values.marketLeasing],
  ];
  for (const [object, group] of groups) {
    for (const key of Object.keys(group)) {
      paths.add(`${object}.${wireFieldName(key)}`);
    }
  }
  return paths;
}

// ---------------------------------------------------------------------------
// Section resolution.
//
// The same `FieldSection[]` shape `buildQuickSections`/`buildDetailedSections`
// produce, so `AssumptionFieldGrid` renders Lease-Level unchanged. Labels,
// prefixes and suffixes are read out of `leaseLevelConvert.ts` rather than
// retyped, so the layout cannot drift from the field configuration.
// ---------------------------------------------------------------------------

function resolveSections<Key extends string>(
  idPrefix: string,
  groups: { title: string; fields: LeaseLevelFieldConfig<Key>[] }[],
  values: Record<Key, string>,
  onChange: (key: Key, value: string) => void,
  errorFor: (key: Key) => string | undefined,
): FieldSection[] {
  return groups.map((group) => ({
    view: null,
    title: group.title,
    fields: group.fields.map((field) => ({
      id: `${idPrefix}-${field.key}`,
      label: field.label,
      prefix: field.prefix,
      suffix: field.suffix,
      value: values[field.key],
      onChange: (value: string) => onChange(field.key, value),
      error: errorFor(field.key),
    })),
  }));
}

interface SelectFieldProps {
  id: string;
  label: string;
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  disabled: boolean;
  error?: string;
  /** Whether an empty choice is a legitimate value on the contract rather than
   * an unmade decision. `renewal_recovery_basis` is genuinely nullable; a lease
   * type is not. */
  nullable?: boolean;
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
}: SelectFieldProps) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <select
        id={id}
        className="field-input"
        value={value}
        disabled={disabled}
        aria-label={error ? label : undefined}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        onChange={(event: ChangeEvent<HTMLSelectElement>) => onChange(event.target.value)}
      >
        {/* An explicit unselected entry. Defaulting to the first option would
            choose an underwriting assumption -- NNN over Gross -- on the
            analyst's behalf, and it would look like a choice they made. */}
        <option value="">{nullable ? 'None' : 'Select…'}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {error && (
        <span className="field-error" id={`${id}-error`} role="alert">
          {error}
        </span>
      )}
    </label>
  );
}

export function LeaseLevelWorkspace({
  values,
  activeSection,
  onSectionChange,
  onTermsFieldChange,
  onPropertyFieldChange,
  onOperatingFieldChange,
  onMarketFieldChange,
  dealContext,
  onDealContextChange,
  isSubmitting,
  leaseIssues,
  termsIssues,
  error,
}: LeaseLevelWorkspaceProps) {
  const anchorable = anchorablePaths(values);
  const unanchored = leaseIssues.filter((issue) => !anchorable.has(issue.path));

  const termsSections: FieldSection[] = TERMS_FIELD_GROUPS.map((group) => ({
    view: null,
    title: group.title,
    fields: group.fields.map((field) => ({
      id: `lease-level-terms-${field.key}`,
      label: field.label,
      prefix: field.prefix,
      suffix: field.suffix,
      value: values.terms[field.key],
      onChange: (value: string) => onTermsFieldChange(field.key, value),
      error: termsMessageFor(termsIssues, TERMS_WIRE_IDS[field.key]),
    })),
  }));

  const propertySections = resolveSections(
    'lease-level-property',
    LEASE_LEVEL_PROPERTY_FIELD_GROUPS,
    values.property,
    onPropertyFieldChange,
    (key) => messageFor(leaseIssues, 'property_inputs', wireFieldName(key)),
  );

  const operatingSections = resolveSections(
    'lease-level-operating',
    LEASE_LEVEL_OPERATING_FIELD_GROUPS,
    values.operating,
    onOperatingFieldChange,
    (key) => messageFor(leaseIssues, 'operating_inputs', wireFieldName(key)),
  );

  const marketSections = resolveSections(
    'lease-level-market',
    LEASE_LEVEL_MARKET_FIELD_GROUPS,
    values.marketLeasing,
    onMarketFieldChange,
    (key) => messageFor(leaseIssues, 'market_leasing', wireFieldName(key)),
  );

  const expenseStopSections: FieldSection[] = [
    {
      view: null,
      title: 'Expense Stops',
      fields: MARKET_LEASING_EXPENSE_STOP_FIELDS.map((field) => ({
        id: `lease-level-market-${field.key}`,
        label: field.label,
        prefix: field.prefix,
        suffix: field.suffix,
        value: values.marketLeasing[field.key],
        onChange: (value: string) => onMarketFieldChange(field.key, value),
        error: messageFor(leaseIssues, 'market_leasing', wireFieldName(field.key)),
      })),
    },
  ];

  const startDateError = messageFor(leaseIssues, 'property_inputs', 'analysis_start_date');

  function panel(id: LeaseLevelSectionId, children: ReactNode) {
    return (
      <div
        id={`lease-level-panel-${id}`}
        role="tabpanel"
        aria-labelledby={`lease-level-tab-${id}`}
        hidden={id !== activeSection}
        className="underwrite-tab-panel"
      >
        {children}
      </div>
    );
  }

  return (
    <div className="underwrite">
      <StrategyStrip value={dealContext} onChange={onDealContextChange} />

      <SubNav
        items={LEASE_LEVEL_SECTIONS}
        active={activeSection}
        onSelect={(id) => onSectionChange(id as LeaseLevelSectionId)}
        label="Lease-Level sections"
        idFor={(id) => `lease-level-tab-${id}`}
        controlsFor={(id) => `lease-level-panel-${id}`}
      />

      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}

      {unanchored.length > 0 && (
        <div className="error-banner" role="alert">
          <ul className="lease-level-issue-list">
            {unanchored.map((issue) => (
              <li key={`${issue.code}-${issue.path}`}>
                {issue.path ? <code>{issue.path}</code> : null} {issue.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="underwrite-body">
        <div className="underwrite-editor">
          {panel(
            'acquisition',
            <AssumptionFieldGrid sections={termsSections} disabled={isSubmitting} />,
          )}

          {panel(
            'property',
            <>
              <div className="assumption-sections">
                <section className="assumption-section">
                  <h3 className="assumption-section-title">Analysis Period</h3>
                  <div className="assumption-field-grid">
                    <label className="field">
                      <span className="field-label">Analysis Start Date</span>
                      {/* A real date control rather than a numeric cell in the
                          shared grid. The value is sent exactly as entered:
                          month alignment is a backend rule
                          (ANALYSIS_START_NOT_MONTH_ALIGNED), never a
                          client-side correction. */}
                      <input
                        id="lease-level-property-analysisStartDate"
                        className="field-input"
                        type="date"
                        value={values.property.analysisStartDate}
                        disabled={isSubmitting}
                        aria-label={startDateError ? 'Analysis Start Date' : undefined}
                        aria-invalid={startDateError ? true : undefined}
                        aria-describedby={
                          startDateError
                            ? 'lease-level-property-analysisStartDate-error'
                            : undefined
                        }
                        onChange={(event: ChangeEvent<HTMLInputElement>) =>
                          onPropertyFieldChange('analysisStartDate', event.target.value)
                        }
                      />
                      {startDateError && (
                        <span
                          className="field-error"
                          id="lease-level-property-analysisStartDate-error"
                          role="alert"
                        >
                          {startDateError}
                        </span>
                      )}
                    </label>
                  </div>
                </section>
              </div>
              <AssumptionFieldGrid sections={propertySections} disabled={isSubmitting} />
            </>,
          )}

          {panel(
            'operating',
            <AssumptionFieldGrid sections={operatingSections} disabled={isSubmitting} />,
          )}

          {panel(
            'market',
            <>
              <p className="field-hint">
                Property-default market leasing. These apply to successor leases the
                rollover engine creates and to vacant space being leased up &mdash; never
                to a signed lease&rsquo;s own contractual terms.
              </p>
              <AssumptionFieldGrid sections={marketSections} disabled={isSubmitting} />
              <div className="assumption-sections">
                <section className="assumption-section">
                  <h3 className="assumption-section-title">Lease Structure &amp; Recoveries</h3>
                  <div className="assumption-field-grid">
                    <SelectField
                      id="lease-level-market-renewalLeaseType"
                      label="Renewal Lease Type"
                      value={values.marketLeasing.renewalLeaseType}
                      options={LEASE_TYPE_OPTIONS}
                      onChange={(next) => onMarketFieldChange('renewalLeaseType', next)}
                      disabled={isSubmitting}
                      error={messageFor(leaseIssues, 'market_leasing', 'renewal_lease_type')}
                    />
                    <SelectField
                      id="lease-level-market-renewalRecoveryBasis"
                      label="Renewal Recovery Basis"
                      value={values.marketLeasing.renewalRecoveryBasis}
                      options={RECOVERY_BASIS_OPTIONS}
                      onChange={(next) => onMarketFieldChange('renewalRecoveryBasis', next)}
                      disabled={isSubmitting}
                      error={messageFor(
                        leaseIssues,
                        'market_leasing',
                        'renewal_recovery_basis',
                      )}
                      nullable
                    />
                    <SelectField
                      id="lease-level-market-newLeaseType"
                      label="New Lease Type"
                      value={values.marketLeasing.newLeaseType}
                      options={LEASE_TYPE_OPTIONS}
                      onChange={(next) => onMarketFieldChange('newLeaseType', next)}
                      disabled={isSubmitting}
                      error={messageFor(leaseIssues, 'market_leasing', 'new_lease_type')}
                    />
                    <SelectField
                      id="lease-level-market-newRecoveryBasis"
                      label="New Recovery Basis"
                      value={values.marketLeasing.newRecoveryBasis}
                      options={RECOVERY_BASIS_OPTIONS}
                      onChange={(next) => onMarketFieldChange('newRecoveryBasis', next)}
                      disabled={isSubmitting}
                      error={messageFor(leaseIssues, 'market_leasing', 'new_recovery_basis')}
                      nullable
                    />
                    <SelectField
                      id="lease-level-market-leasingCommissionMethod"
                      label="Leasing Commission Method"
                      value={values.marketLeasing.leasingCommissionMethod}
                      options={LEASING_COMMISSION_METHOD_OPTIONS}
                      onChange={(next) => onMarketFieldChange('leasingCommissionMethod', next)}
                      disabled={isSubmitting}
                      error={messageFor(
                        leaseIssues,
                        'market_leasing',
                        'leasing_commission_method',
                      )}
                    />
                  </div>
                </section>
              </div>
              <AssumptionFieldGrid sections={expenseStopSections} disabled={isSubmitting} />
            </>,
          )}

          {panel(
            'rent-roll',
            <div className="assumption-sections">
              <section className="assumption-section">
                <h3 className="assumption-section-title">Rent Roll</h3>
                {values.suites.length === 0 ? (
                  <p className="field-hint">
                    No suites yet. Suite and lease entry arrives in the next gate; until
                    then a Lease-Level analysis needs a rent roll loaded from a saved
                    deal.
                  </p>
                ) : (
                  <>
                    <dl className="lease-level-roll-counts">
                      <div>
                        <dt>Suites</dt>
                        <dd>{values.suites.length}</dd>
                      </div>
                      <div>
                        <dt>Leases</dt>
                        <dd>{values.leases.length}</dd>
                      </div>
                    </dl>
                    <p className="field-hint">
                      Loaded from the saved deal and carried through every edit unchanged.
                      Editing arrives in the next gate.
                    </p>
                  </>
                )}
              </section>
            </div>,
          )}
        </div>
      </div>
    </div>
  );
}
