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
import { LeaseLevelResults } from './LeaseLevelResults';
import { RentRollTable } from './RentRollTable';
import { SuiteLeaseEditor } from './SuiteLeaseEditor';
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
  reconcileArea,
  wireFieldName,
} from '../leaseLevelConvert';
import type { LeaseLevelFieldConfig, SelectOption } from '../leaseLevelConvert';
import { TERMS_FIELD_GROUPS } from '../convert';
import type { FieldSection, ResultsViewId } from '../underwrite';
import type { OperatingPeriodView } from './LeaseLevelOperatingStatement';
import type {
  InitialVacancyFormValues,
  LeaseFormValues,
  LeaseLevelAcquisitionResults,
  LeaseLevelFormValues,
  LeaseLevelIssue,
  LeaseLevelOperatingFormValues,
  LeaseLevelPropertyFormValues,
  MarketLeasingFormValues,
} from '../leaseLevelTypes';
import type { RowIssues } from '../leaseLevelIssues';
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
  | 'rent-roll'
  | 'results';

/* Not exported: a component module that also exports values loses fast
 * refresh, and nothing outside this file needs the list. */
const LEASE_LEVEL_SECTIONS: { id: LeaseLevelSectionId; label: string }[] = [
  { id: 'acquisition', label: 'Acquisition & Debt' },
  { id: 'property', label: 'Property' },
  { id: 'operating', label: 'Operating' },
  { id: 'market', label: 'Market Leasing' },
  { id: 'rent-roll', label: 'Rent Roll' },
  { id: 'results', label: 'Results' },
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

  // --- D5.5B: the rent roll -------------------------------------------------
  /** Rent-roll issues already resolved to the row that produced them. */
  issuesByRow: Map<string, RowIssues>;
  /** Display-only area reconciliation. Never financial authority. */
  area: AreaReconciliationValues;
  editorRowId: string | null;
  onOpenEditor: (rowId: string) => void;
  onCloseEditor: () => void;
  onAddRow: () => void;
  onDeleteRow: (rowId: string) => void;
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
  onToggleOccupancy: (rowId: string) => void;
  onUseSuiteArea: (rowId: string) => void;

  // --- D5.6: results ---------------------------------------------------------
  /** The analysis describing the *current* inputs, or `null`. Never a stored
   * snapshot: Lease-Level persists none, and any edit clears this. */
  analysis: LeaseLevelAcquisitionResults | null;
  isAnalyzing: boolean;
  resultsView: ResultsViewId;
  onResultsViewChange: (view: ResultsViewId) => void;
  periodView: OperatingPeriodView;
  onPeriodViewChange: (view: OperatingPeriodView) => void;

  // --- D6.6: the Business Plan ----------------------------------------------
  /** The shared Business Plan editor, bound to this deal's plan by the shell.
   * Rendered on Acquisition & Debt, apart from the rent roll and the market
   * leasing assumptions that drive TI / LC -- Project Capital is not leasing
   * capital, and is never placed beside it. */
  businessPlan: ReactNode;
}

export type AreaReconciliationValues = ReturnType<typeof reconcileArea>;

/**
 * The D5.0 display-only area carve-out, rendered.
 *
 * Addition of integers the analyst typed, labelled as the input aid it is. It
 * changes no value, allocates nothing, creates no residual suite and blocks no
 * submission -- `RENTABLE_AREA_NOT_RECONCILED` from the backend is still the
 * only thing that can refuse an analysis, and this deliberately does not claim
 * to be that.
 */
function AreaReconciliation({
  area,
  rows,
}: {
  area: AreaReconciliationValues;
  rows: number;
}) {
  const { rentableAreaSf, allocatedSf, differenceSf, rowsWithoutArea } = area;
  const reconciled = differenceSf === 0 && rowsWithoutArea === 0;

  return (
    <section className="area-reconciliation" aria-label="Area reconciliation">
      <dl className="area-reconciliation-figures">
        <div>
          <dt>Suites</dt>
          <dd>{rows}</dd>
        </div>
        <div>
          <dt>Property Rentable Area</dt>
          <dd>{rentableAreaSf === null ? '—' : `${formatArea(rentableAreaSf)} SF`}</dd>
        </div>
        <div>
          <dt>Allocated Suite Area</dt>
          <dd>{`${formatArea(allocatedSf)} SF`}</dd>
        </div>
        <div>
          <dt>Difference</dt>
          <dd>{differenceSf === null ? '—' : `${formatArea(differenceSf)} SF`}</dd>
        </div>
      </dl>
      <p className={reconciled ? 'area-reconciliation-note' : 'area-reconciliation-note area-reconciliation-note-warn'}>
        {rentableAreaSf === null
          ? 'Enter the property rentable area on the Property tab to compare suite areas against it.'
          : rowsWithoutArea > 0
            ? `${rowsWithoutArea} suite${rowsWithoutArea === 1 ? '' : 's'} without an area yet — this total is incomplete.`
            : reconciled
              ? 'Suite areas match the property rentable area.'
              : differenceSf! > 0
                ? `Suite areas are ${formatArea(differenceSf!)} SF below the property rentable area.`
                : `Suite areas exceed the property rentable area by ${formatArea(Math.abs(differenceSf!))} SF.`}
      </p>
    </section>
  );
}

/** Thousands separators for a whole number of square feet. Presentation only:
 * it rounds nothing and computes nothing. */
function formatArea(value: number): string {
  return value.toLocaleString('en-US', { maximumFractionDigits: 2 });
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
  issuesByRow,
  area,
  editorRowId,
  onOpenEditor,
  onCloseEditor,
  onAddRow,
  onDeleteRow,
  onSuiteFieldChange,
  onLeaseFieldChange,
  onVacancyFieldChange,
  onOverrideFieldChange,
  onToggleOverride,
  onToggleOccupancy,
  onUseSuiteArea,
  analysis,
  isAnalyzing,
  resultsView,
  onResultsViewChange,
  periodView,
  onPeriodViewChange,
  businessPlan,
}: LeaseLevelWorkspaceProps) {
  const editorRow = values.rentRoll.find((row) => row.rowId === editorRowId);
  const anchorable = anchorablePaths(values);
  // D5.5B: a rent-roll path is anchored when a row actually claimed it. Rows
  // report which paths they resolved, so an issue naming a row that no longer
  // exists still reaches the banner rather than disappearing with the row.
  const claimedByRows = new Set<string>();
  for (const row of issuesByRow.values()) {
    for (const issue of row.fields.values()) {
      claimedByRows.add(issue.path);
    }
    for (const issue of row.rowLevel) {
      claimedByRows.add(issue.path);
    }
  }
  const unanchored = leaseIssues.filter(
    (issue) => !anchorable.has(issue.path) && !claimedByRows.has(issue.path),
  );

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
    // D5.5E: the rent roll uses the widened panel; the scalar sections stay at
    // the normal readable measure inside it. A column of labelled inputs
    // stretched to 1800px is harder to read, not easier.
    // The rent roll and the result statements are both analyst-dense grids;
    // the four assumption tabs keep the readable measure.
    const scalar = id !== 'rent-roll' && id !== 'results';
    return (
      <div
        id={`lease-level-panel-${id}`}
        role="tabpanel"
        aria-labelledby={`lease-level-tab-${id}`}
        hidden={id !== activeSection}
        className={
          scalar ? 'underwrite-tab-panel lease-level-scalar-panel' : 'underwrite-tab-panel'
        }
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
            <>
              <AssumptionFieldGrid sections={termsSections} disabled={isSubmitting} />
              {businessPlan}
            </>,
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
                Property defaults for leasing that has not happened yet. These apply
                to the lease that follows each current lease when it expires, and to
                vacant space being leased up &mdash; never to a signed lease&rsquo;s own
                contractual terms.
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
                      label="New Tenant Lease Type"
                      value={values.marketLeasing.newLeaseType}
                      options={LEASE_TYPE_OPTIONS}
                      onChange={(next) => onMarketFieldChange('newLeaseType', next)}
                      disabled={isSubmitting}
                      error={messageFor(leaseIssues, 'market_leasing', 'new_lease_type')}
                    />
                    <SelectField
                      id="lease-level-market-newRecoveryBasis"
                      label="New Tenant Recovery Basis"
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
            <div className="rent-roll-panel">
              <AreaReconciliation area={area} rows={values.rentRoll.length} />

              <RentRollTable
                rows={values.rentRoll}
                issuesByRow={issuesByRow}
                disabled={isSubmitting}
                onSuiteFieldChange={onSuiteFieldChange}
                onLeaseFieldChange={onLeaseFieldChange}
                onToggleOccupancy={onToggleOccupancy}
                onOpenEditor={onOpenEditor}
                onDeleteRow={onDeleteRow}
                onAddRow={onAddRow}
              />

              {editorRow !== undefined && (
                <SuiteLeaseEditor
                  row={editorRow}
                  issues={issuesByRow.get(editorRow.rowId)}
                  disabled={isSubmitting}
                  onClose={onCloseEditor}
                  onSuiteFieldChange={onSuiteFieldChange}
                  onLeaseFieldChange={onLeaseFieldChange}
                  onVacancyFieldChange={onVacancyFieldChange}
                  onOverrideFieldChange={onOverrideFieldChange}
                  onToggleOverride={onToggleOverride}
                  onUseSuiteArea={onUseSuiteArea}
                />
              )}
            </div>,
          )}

          {panel(
            'results',
            <LeaseLevelResults
              analysis={analysis}
              isAnalyzing={isAnalyzing}
              view={resultsView}
              onViewChange={onResultsViewChange}
              periodView={periodView}
              onPeriodViewChange={onPeriodViewChange}
            />,
          )}
        </div>
      </div>
    </div>
  );
}
