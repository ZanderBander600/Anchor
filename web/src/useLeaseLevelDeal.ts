/**
 * D5.5A -- all Lease-Level workspace state, in one hook.
 *
 * `App.tsx` already carries two fully parallel state trees, one per mode, and
 * the D5.0 review removed extracting them from this sprint's scope. Adding a
 * third inline would have meant roughly two hundred more lines in a 2,500-line
 * component -- and would have made D5.5B's rent-roll editors land in the same
 * file as Quick's and Detailed's assumptions.
 *
 * So Lease-Level's state lives here instead. The shell gains one `useLeaseLevelDeal()`
 * call and reads the result; it gains no new `useState`. Quick's and Detailed's
 * state is not touched, moved or reshaped, which is what keeps this gate's
 * promise that no existing behaviour changes.
 *
 * The shapes mirror Detailed's persistence state deliberately -- same dirty
 * snapshot, same `SaveStatus` derivation, same "reset downstream analysis on any
 * input edit" rule -- so the three modes stay recognisably the same product.
 *
 * **It computes no economics.** Every value here is a string the analyst typed,
 * a row loaded from a saved deal, or a flag about the request in flight.
 */

import { useState } from 'react';
import {
  ApiError,
  LeaseLevelApiError,
  analyzeLeaseLevelAcquisition,
  createLeaseLevelDeal,
  getDeal,
  updateLeaseLevelDeal,
} from './api';
import { FormValidationError, buildDetailedTermsFormValuesFromRequest } from './convert';
import {
  BLANK_LEASE_LEVEL_FORM_VALUES,
  blankLeaseFormValues,
  blankSuiteRow,
  buildLeaseLevelFormValues,
  buildLeaseLevelInputsRequest,
  buildLeaseLevelTermsRequest,
  collectBlankScalarIssues,
  collectRentRollBlankIssues,
  isRowOccupied,
  reconcileArea,
} from './leaseLevelConvert';
import { EMPTY_SUBMITTED_RENT_ROLL, resolveRowIssues } from './leaseLevelIssues';
import type { RowIssues, SubmittedRentRoll } from './leaseLevelIssues';
import type { LeaseLevelSectionId } from './components/LeaseLevelWorkspace';
import type { OperatingPeriodView } from './components/LeaseLevelOperatingStatement';
import type { ResultsViewId } from './underwrite';
import type { SaveStatus } from './components/DealHeader';
import type {
  InitialVacancyFormValues,
  LeaseFormValues,
  LeaseLevelAcquisitionResults,
  LeaseLevelFormValues,
  LeaseLevelInputsRequest,
  LeaseLevelIssue,
  LeaseLevelOperatingFormValues,
  LeaseLevelPropertyFormValues,
  MarketLeasingFormValues,
  SuiteRowFormValues,
} from './leaseLevelTypes';
import type {
  AcquisitionTermsFormValues,
  AcquisitionTermsRequest,
  Deal,
  ValidationIssue,
} from './types';

/** What the shell needs to know about a saved Lease-Level deal, plus the
 * handlers it wires into the header and the workspace. */
export interface LeaseLevelDealState {
  values: LeaseLevelFormValues;
  dealName: string;
  dealContext: string;
  currentDealId: string | null;
  saveStatus: SaveStatus;
  lastSavedAt: string | null;
  isDirty: boolean;

  activeSection: LeaseLevelSectionId;
  setActiveSection: (section: LeaseLevelSectionId) => void;
  /** Which result view is open, and whether the statement shows months or
   * years. View state only -- neither changes a number. */
  resultsView: ResultsViewId;
  setResultsView: (view: ResultsViewId) => void;
  periodView: OperatingPeriodView;
  setPeriodView: (view: OperatingPeriodView) => void;

  /** The analysis describing the assumptions currently on screen, or `null`.
   *
   * Cleared by `resetDownstream` on every input edit, so it can never describe
   * inputs the analyst has since changed, and never restored on open, because
   * Lease-Level persists no snapshot (decision D5). Those two rules together
   * are why no staleness indicator is needed: a result that is visible is a
   * result that is current. */
  results: LeaseLevelAcquisitionResults | null;
  isAnalyzing: boolean;
  isSaving: boolean;
  /** The whole-request message from the last failure, analysis or save. */
  error: string | null;
  /** The save-specific message the deal header renders, kept separate from
   * `error` exactly as Quick and Detailed keep theirs. */
  saveError: string | null;
  leaseIssues: LeaseLevelIssue[];
  termsIssues: ValidationIssue[];
  /** Rent-roll issues from the last refused submission, already resolved to the
   * row that produced them against the array that was actually submitted. */
  issuesByRow: Map<string, RowIssues>;
  /** The row whose advanced editor is open, or `null`. */
  editorRowId: string | null;
  openEditor: (rowId: string) => void;
  closeEditor: () => void;
  /** Display-only area reconciliation (D5.0 carve-out). Never authority. */
  area: ReturnType<typeof reconcileArea>;

  addRow: () => void;
  deleteRow: (rowId: string) => void;
  updateSuiteField: (
    rowId: string,
    key: 'suiteId' | 'suiteAreaSf' | 'suiteLabel' | 'marketRentPsf',
    value: string,
  ) => void;
  updateLeaseField: (
    rowId: string,
    key: keyof Omit<LeaseFormValues, 'origin'>,
    value: string,
  ) => void;
  updateVacancyField: (
    rowId: string,
    key: keyof InitialVacancyFormValues,
    value: string,
  ) => void;
  updateOverrideField: (
    rowId: string,
    key: keyof MarketLeasingFormValues,
    value: string,
  ) => void;
  toggleOverride: (rowId: string) => void;
  toggleOccupancy: (rowId: string) => void;
  useSuiteArea: (rowId: string) => void;

  onTermsFieldChange: (key: keyof AcquisitionTermsFormValues, value: string) => void;
  onPropertyFieldChange: (key: keyof LeaseLevelPropertyFormValues, value: string) => void;
  onOperatingFieldChange: (key: keyof LeaseLevelOperatingFormValues, value: string) => void;
  onMarketFieldChange: (key: keyof MarketLeasingFormValues, value: string) => void;
  onDealNameChange: (value: string) => void;
  onDealContextChange: (value: string) => void;

  /**
   * D5.7 -- the request Analyze would submit, built from the assumptions
   * currently on screen.
   *
   * Exposed so the sensitivity workspace runs against the **current** inputs
   * rather than a saved deal, a stale snapshot or the last analysis, and does so
   * through the one authoritative mapper. There is deliberately no second
   * Lease-Level request builder: this is literally the function `analyze` and
   * `save` call.
   *
   * Returns `null` when a field is still blank, having reported those blanks on
   * the tabs that hold them exactly as Analyze does. Calling it neither dirties
   * the deal, clears the analysis, nor persists anything.
   */
  buildRequest: () => { terms: AcquisitionTermsRequest; inputs: LeaseLevelInputsRequest } | null;

  analyze: () => Promise<void>;
  save: () => Promise<void>;
  /** Loads a saved Lease-Level deal into this state. Returns `false` when the
   * analyst declined to discard unsaved work, so the shell knows not to switch
   * mode. Any failure is reported through the thrown `ApiError`, which the
   * shell already handles for the other two modes. */
  open: (dealId: string) => Promise<boolean>;
  resetToBlank: () => void;
  confirmDiscardIfDirty: () => boolean;
}

/** The one message for "a field is still blank, so no request exists to send".
 *
 * Module scope since D5.7, because the sensitivity workspace builds the same
 * request through the same mapper and must say the same thing when it cannot. */
export const LEASE_LEVEL_BLANKS_MESSAGE =
  'Some assumptions are still blank. They are marked on the tab that holds them.';

interface LeaseLevelSnapshot {
  dealName: string;
  values: LeaseLevelFormValues;
  dealContext: string;
}

const BLANK_SNAPSHOT: LeaseLevelSnapshot = {
  dealName: '',
  values: BLANK_LEASE_LEVEL_FORM_VALUES,
  dealContext: '',
};

/**
 * Dirty comparison over everything the deal submits.
 *
 * D5.5A compared scalars and the two rent-roll arrays by identity, which was
 * sound while nothing could edit a row. D5.5B can, so the field-by-field array
 * comparison the plan called for (§10) lands here.
 */
function isSameSnapshot(a: LeaseLevelSnapshot, b: LeaseLevelSnapshot): boolean {
  if (a.dealName !== b.dealName || a.dealContext !== b.dealContext) {
    return false;
  }
  // D5.5B: the rent roll is editable, so it joins the one dirty-state system
  // rather than getting a flag of its own that could disagree with it.
  if (!isSameRentRoll(a.values.rentRoll, b.values.rentRoll)) {
    return false;
  }
  const groups = ['terms', 'property', 'operating', 'marketLeasing'] as const;
  return groups.every((group) => {
    // Keyed off the values actually present rather than a hand-written field
    // list: a field added to any of the four form contracts joins this
    // comparison automatically, so a new assumption cannot be edited without
    // marking the deal dirty.
    const left = Object.entries(a.values[group]);
    const right = new Map<string, unknown>(Object.entries(b.values[group]));
    return (
      left.length === right.size && left.every(([key, value]) => right.get(key) === value)
    );
  });
}

// =============================================================================
// D5.5B -- rent-roll editing
//
// Every operation below is structural: it adds, removes or retypes a row, or
// moves a value between the states the contract can represent. None computes an
// economic quantity, and none invents one.
// =============================================================================

/**
 * Field-by-field comparison of two rent rolls.
 *
 * Not `JSON.stringify`: key order is an artefact of whichever code built the
 * object, so two identical rolls -- one loaded, one edited back to the same
 * values -- would compare unequal. Not a generic deep-equal either; this walks
 * the shapes it actually has, so a field added to a form contract shows up here
 * as a compile error rather than as a silently unwatched field.
 *
 * **It compares what would be submitted, and only that.** `rowId` is local UI
 * identity. Dormant state -- an override the row is not using, a vacancy
 * treatment on an occupied suite, a lease-up figure under Hold Vacant -- is held
 * for the analyst's convenience but never sent, so counting it would mark a deal
 * dirty that saves to identical bytes and then reports "saved" having discarded
 * the edit.
 */
function isSameLease(a: LeaseFormValues | null, b: LeaseFormValues | null): boolean {
  if (a === null || b === null) {
    return a === b;
  }
  return (
    a.leaseId === b.leaseId &&
    a.leasedAreaSf === b.leasedAreaSf &&
    a.tenantName === b.tenantName &&
    a.leaseStartDate === b.leaseStartDate &&
    a.rentCommencementDate === b.rentCommencementDate &&
    a.leaseExpirationDate === b.leaseExpirationDate &&
    a.baseRentPsf === b.baseRentPsf &&
    a.escalationPct === b.escalationPct &&
    a.escalationBasis === b.escalationBasis &&
    a.leaseType === b.leaseType &&
    a.recoveryBasis === b.recoveryBasis &&
    a.expenseStopPsf === b.expenseStopPsf &&
    a.origin === b.origin
  );
}

function isSameStringRecord(a: object, b: object): boolean {
  const left = Object.entries(a);
  const right = new Map<string, unknown>(Object.entries(b));
  return left.length === right.size && left.every(([key, value]) => right.get(key) === value);
}

function isSameVacancy(a: SuiteRowFormValues, b: SuiteRowFormValues): boolean {
  // An occupied suite submits no treatment at all, so neither row's dormant
  // values matter while both are occupied.
  if (isRowOccupied(a) || isRowOccupied(b)) {
    return isRowOccupied(a) === isRowOccupied(b);
  }
  if (a.initialVacancy.strategy !== b.initialVacancy.strategy) {
    return false;
  }
  // The lease-up figure only travels under Market Lease-Up.
  if (a.initialVacancy.strategy !== 'market_lease_up') {
    return true;
  }
  return a.initialVacancy.initialLeaseUpMonths === b.initialVacancy.initialLeaseUpMonths;
}

function isSameRentRoll(
  a: readonly SuiteRowFormValues[],
  b: readonly SuiteRowFormValues[],
): boolean {
  if (a.length !== b.length) {
    return false;
  }
  return a.every((row, index) => {
    const other = b[index];
    if (
      row.suiteId !== other.suiteId ||
      row.suiteAreaSf !== other.suiteAreaSf ||
      row.suiteLabel !== other.suiteLabel ||
      row.marketRentPsf !== other.marketRentPsf ||
      row.marketLeasingOverrideEnabled !== other.marketLeasingOverrideEnabled
    ) {
      return false;
    }
    if (!isSameLease(row.lease, other.lease) || !isSameVacancy(row, other)) {
      return false;
    }
    // A disabled override submits `null` whatever it holds.
    return (
      !row.marketLeasingOverrideEnabled ||
      isSameStringRecord(row.marketLeasingOverride, other.marketLeasingOverride)
    );
  });
}

export function useLeaseLevelDeal(options: {
  /** Called after a successful save so the shared Deal Library refreshes --
   * the same callback Quick and Detailed already use. */
  onDealsChanged: () => void;
  /** Called when opening a deal should land the analyst somewhere. Lease-Level
   * always lands on Underwrite: no analysis snapshot is persisted for this mode
   * (decision D5), so Overview would be empty. */
  onOpened: () => void;
}): LeaseLevelDealState {
  const [values, setValues] = useState<LeaseLevelFormValues>(BLANK_LEASE_LEVEL_FORM_VALUES);
  const [dealName, setDealName] = useState('');
  const [dealContext, setDealContext] = useState('');
  const [currentDealId, setCurrentDealId] = useState<string | null>(null);
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);
  const [savedSnapshot, setSavedSnapshot] = useState<LeaseLevelSnapshot>(BLANK_SNAPSHOT);
  const [activeSection, setActiveSection] = useState<LeaseLevelSectionId>('acquisition');
  const [resultsView, setResultsView] = useState<ResultsViewId>('summary');
  const [periodView, setPeriodView] = useState<OperatingPeriodView>('annual');

  const [results, setResults] = useState<LeaseLevelAcquisitionResults | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [leaseIssues, setLeaseIssues] = useState<LeaseLevelIssue[]>([]);
  const [termsIssues, setTermsIssues] = useState<ValidationIssue[]>([]);
  const [editorRowId, setEditorRowId] = useState<string | null>(null);
  // What the last submission actually sent. Backend issue paths carry array
  // indices, and those mean nothing against state the analyst has edited since,
  // so they are resolved against this rather than against the current roll.
  const [submitted, setSubmitted] = useState<SubmittedRentRoll>(EMPTY_SUBMITTED_RENT_ROLL);

  const isDirty = !isSameSnapshot({ dealName, values, dealContext }, savedSnapshot);
  const saveStatus: SaveStatus =
    currentDealId === null ? 'unsaved-deal' : isDirty ? 'unsaved-changes' : 'saved';

  /** Editing any assumption invalidates the analysis that was run on the old
   * ones, and clears the issues raised against them -- the same rule Quick and
   * Detailed apply. Results are dropped, never recomputed automatically. */
  function resetDownstream() {
    setResults(null);
    setError(null);
    setLeaseIssues([]);
    setTermsIssues([]);
    setSubmitted(EMPTY_SUBMITTED_RENT_ROLL);
  }

  function recordFailure(caught: unknown, fallback: string): string {
    if (caught instanceof LeaseLevelApiError) {
      setLeaseIssues(caught.leaseIssues);
      setTermsIssues(caught.issues);
      return caught.message;
    }
    setLeaseIssues([]);
    setTermsIssues([]);
    if (caught instanceof ApiError) {
      return caught.message;
    }
    if (caught instanceof FormValidationError) {
      return caught.message;
    }
    return fallback;
  }

  function onTermsFieldChange(key: keyof AcquisitionTermsFormValues, value: string) {
    setValues((previous) => ({ ...previous, terms: { ...previous.terms, [key]: value } }));
    resetDownstream();
  }

  function onPropertyFieldChange(key: keyof LeaseLevelPropertyFormValues, value: string) {
    setValues((previous) => ({ ...previous, property: { ...previous.property, [key]: value } }));
    resetDownstream();
  }

  function onOperatingFieldChange(key: keyof LeaseLevelOperatingFormValues, value: string) {
    setValues((previous) => ({
      ...previous,
      operating: { ...previous.operating, [key]: value },
    }));
    resetDownstream();
  }

  function onMarketFieldChange(key: keyof MarketLeasingFormValues, value: string) {
    setValues((previous) => ({
      ...previous,
      marketLeasing: { ...previous.marketLeasing, [key]: value },
    }));
    resetDownstream();
  }

  /** Deal Context is not a financial input, so it marks the deal dirty without
   * invalidating a deterministic analysis -- exactly Detailed's rule. */
  function onDealContextChange(value: string) {
    setDealContext(value);
  }

  /**
   * Submit and surface, never disable.
   *
   * The Analyze and Save buttons are always live. This client does not decide
   * whether a Lease-Level deal is complete or sound -- that is the backend's
   * question, and a second validity rule sitting in front of the authoritative
   * one would drift the moment a contract changed. The one thing this gate will
   * not do is invent a suite so that a blank deal can analyze.
   *
   * The single exception is not a judgement about the deal: a field left blank
   * cannot become a value at all, so no request exists to send. Those are
   * collected up front and anchored to their fields -- all of them, rather than
   * the first, which is what `parseNumber` alone would report and what would
   * turn a forty-seven-field form into forty-seven round trips. Everything the
   * transport can express is sent, and the answer that comes back is the only
   * one that decides anything.
   *
   * Returns the built request, or `null` when it reported blanks instead.
   */
  /** Which local row produced each entry of the arrays being reported on.
   *
   * Backend issue paths carry array indices, and an index means nothing against
   * state the analyst has edited since the request went out -- resolving
   * `suites[2]` against the current roll would blame whichever suite happens to
   * sit there now. Captured here, at the moment of submission, so every index
   * resolves to a stable local row id.
   *
   * `orderedLeaseSuiteIds` is the suite each submitted lease belongs to, in the
   * order the leases were actually emitted; `null` means row order, which is
   * what the blank collector uses since nothing is sent. */
  function captureSubmitted(orderedLeaseSuiteIds: string[] | null): void {
    const occupied = values.rentRoll.filter((row) => row.lease !== null);
    setSubmitted({
      suiteRowIds: values.rentRoll.map((row) => row.rowId),
      suiteIds: values.rentRoll.map((row) => row.suiteId.trim()),
      leaseRowIds:
        orderedLeaseSuiteIds === null
          ? occupied.map((row) => row.rowId)
          : orderedLeaseSuiteIds.map(
              (suiteId) =>
                occupied.find((row) => row.suiteId.trim() === suiteId)?.rowId ?? '',
            ),
    });
  }

  function buildRequest(): { terms: AcquisitionTermsRequest; inputs: LeaseLevelInputsRequest } | null {
    const blanks = collectBlankScalarIssues(values);
    const rowBlanks = collectRentRollBlankIssues(values);
    if (
      blanks.leaseIssues.length > 0 ||
      blanks.termsIssues.length > 0 ||
      rowBlanks.length > 0
    ) {
      captureSubmitted(null);
      setLeaseIssues([...blanks.leaseIssues, ...rowBlanks]);
      setTermsIssues(blanks.termsIssues);
      return null;
    }
    const inputs = buildLeaseLevelInputsRequest(values);
    captureSubmitted(inputs.leases.map((lease) => lease.suite_id));

    return {
      terms: buildLeaseLevelTermsRequest(values.terms),
      inputs,
    };
  }

  async function analyze(): Promise<void> {
    setIsAnalyzing(true);
    setError(null);
    setLeaseIssues([]);
    setTermsIssues([]);
    try {
      const request = buildRequest();
      if (request === null) {
        setError(LEASE_LEVEL_BLANKS_MESSAGE);
        return;
      }
      const analysis = await analyzeLeaseLevelAcquisition(request.terms, request.inputs);
      setResults(analysis);
      // D5.6: Analyze must visibly do something. Landing on Results is what
      // makes a successful run self-evident rather than something the analyst
      // has to go looking for.
      setActiveSection('results');
    } catch (caught) {
      setResults(null);
      setError(recordFailure(caught, 'An unexpected error occurred while analyzing the deal.'));
    } finally {
      setIsAnalyzing(false);
    }
  }

  /**
   * Save / Update.
   *
   * The same policy as Analyze, for the same reason. Saving persists inputs
   * only -- Lease-Level caches no analysis snapshot (decision D5), so there is
   * no fingerprint call and no snapshot attachment here, and reopening re-runs
   * the engine.
   *
   * A partly-filled deal therefore cannot be saved yet, which is a real
   * limitation and is stated as one: the backend's Lease-Level deal contract
   * has no partial form, and inventing zeros to fill the gaps would persist
   * assumptions the analyst never made.
   */
  async function save(): Promise<void> {
    setIsSaving(true);
    setSaveError(null);
    setLeaseIssues([]);
    setTermsIssues([]);
    try {
      const request = buildRequest();
      if (request === null) {
        setSaveError(LEASE_LEVEL_BLANKS_MESSAGE);
        return;
      }
      const { terms, inputs } = request;
      const name = dealName.trim() || 'Untitled Deal';
      const context = dealContext.trim() || null;
      const deal = currentDealId
        ? await updateLeaseLevelDeal(currentDealId, name, terms, inputs, context)
        : await createLeaseLevelDeal(name, terms, inputs, context);
      setCurrentDealId(deal.id);
      setDealName(deal.name);
      setDealContext(deal.deal_context ?? '');
      setLastSavedAt(deal.updated_at);
      setSavedSnapshot({ dealName: deal.name, values, dealContext: deal.deal_context ?? '' });
      options.onDealsChanged();
    } catch (caught) {
      setSaveError(recordFailure(caught, 'An unexpected error occurred while saving the deal.'));
    } finally {
      setIsSaving(false);
    }
  }

  function hydrate(deal: Deal): void {
    if (
      deal.terms === null ||
      deal.property_inputs === null ||
      deal.operating_inputs === null ||
      deal.market_leasing === null ||
      deal.suites === null ||
      deal.leases === null
    ) {
      throw new Error('Lease-Level deal is missing its inputs.');
    }
    // The rent roll is taken as it arrived -- the transport objects themselves,
    // not a re-encoding of them. Round-tripping rows through a form
    // representation this gate cannot render would risk changing a saved rent
    // roll on a screen that never shows it.
    const opened = buildLeaseLevelFormValues(
      {
        terms: deal.terms,
        property_inputs: deal.property_inputs,
        operating_inputs: deal.operating_inputs,
        market_leasing: deal.market_leasing,
        suites: deal.suites,
        leases: deal.leases,
      },
      // The same `AcquisitionTerms` decoder Detailed reopens with, unchanged:
      // `terms` is one shared contract across both modes, so a reopened
      // purchase price is decoded by exactly one function.
      buildDetailedTermsFormValuesFromRequest(deal.terms),
    );
    setValues(opened);
    setDealName(deal.name);
    setDealContext(deal.deal_context ?? '');
    setCurrentDealId(deal.id);
    setLastSavedAt(deal.updated_at);
    setSavedSnapshot({
      dealName: deal.name,
      values: opened,
      dealContext: deal.deal_context ?? '',
    });
    setActiveSection('acquisition');
    setEditorRowId(null);
    setSubmitted(EMPTY_SUBMITTED_RENT_ROLL);
    setResults(null);
    setError(null);
    setSaveError(null);
    setLeaseIssues([]);
    setTermsIssues([]);
  }

  async function open(dealId: string): Promise<boolean> {
    if (!confirmDiscardIfDirty()) {
      return false;
    }
    hydrate(await getDeal(dealId));
    options.onOpened();
    return true;
  }

  function resetToBlank(): void {
    setValues(BLANK_LEASE_LEVEL_FORM_VALUES);
    setDealName('');
    setDealContext('');
    setCurrentDealId(null);
    setLastSavedAt(null);
    setSavedSnapshot(BLANK_SNAPSHOT);
    setActiveSection('acquisition');
    setEditorRowId(null);
    setSubmitted(EMPTY_SUBMITTED_RENT_ROLL);
    setResults(null);
    setError(null);
    setSaveError(null);
    setLeaseIssues([]);
    setTermsIssues([]);
  }

  function confirmDiscardIfDirty(): boolean {
    if (!isDirty) {
      return true;
    }
    return window.confirm('You have unsaved changes that will be lost. Continue?');
  }

  // ===========================================================================
  // D5.5B -- rent-roll operations
  // ===========================================================================

  /** Applies a change to one row, addressed by its local id. */
  function updateRow(rowId: string, change: (row: SuiteRowFormValues) => SuiteRowFormValues) {
    setValues((previous) => ({
      ...previous,
      rentRoll: previous.rentRoll.map((row) => (row.rowId === rowId ? change(row) : row)),
    }));
    resetDownstream();
  }

  function addRow(): void {
    setValues((previous) => ({ ...previous, rentRoll: [...previous.rentRoll, blankSuiteRow()] }));
    resetDownstream();
  }

  /** True when a row holds anything the analyst typed. Used to decide whether
   * deleting it needs confirmation -- an untouched blank row is not data. */
  function rowHasContent(row: SuiteRowFormValues): boolean {
    if (
      row.suiteId.trim() !== '' ||
      row.suiteAreaSf.trim() !== '' ||
      row.suiteLabel.trim() !== '' ||
      row.marketRentPsf.trim() !== '' ||
      row.marketLeasingOverrideEnabled
    ) {
      return true;
    }
    if (row.initialVacancy.strategy !== '') {
      return true;
    }
    return row.lease !== null && leaseHasContent(row.lease);
  }

  function leaseHasContent(lease: LeaseFormValues): boolean {
    return Object.entries(lease).some(
      ([key, value]) => key !== 'origin' && typeof value === 'string' && value.trim() !== '',
    );
  }

  /** Deletes a row, and with it the one lease it carried.
   *
   * Removing the row removes its lease from the submitted roll by construction:
   * leases are emitted from rows, so there is no separate array left holding a
   * lease that references a suite that no longer exists. */
  function deleteRow(rowId: string): void {
    const row = values.rentRoll.find((candidate) => candidate.rowId === rowId);
    if (row === undefined) {
      return;
    }
    if (rowHasContent(row)) {
      const name = row.suiteId.trim() === '' ? 'this suite' : `suite ${row.suiteId.trim()}`;
      const carriesLease = row.lease !== null && leaseHasContent(row.lease);
      const detail = carriesLease ? ' Its lease will be removed with it.' : '';
      if (!window.confirm(`Delete ${name}?${detail} This cannot be undone.`)) {
        return;
      }
    }
    setValues((previous) => ({
      ...previous,
      rentRoll: previous.rentRoll.filter((candidate) => candidate.rowId !== rowId),
    }));
    if (editorRowId === rowId) {
      setEditorRowId(null);
    }
    resetDownstream();
  }

  function updateSuiteField(
    rowId: string,
    key: 'suiteId' | 'suiteAreaSf' | 'suiteLabel' | 'marketRentPsf',
    value: string,
  ): void {
    updateRow(rowId, (row) => ({ ...row, [key]: value }));
  }

  function updateLeaseField(
    rowId: string,
    key: keyof Omit<LeaseFormValues, 'origin'>,
    value: string,
  ): void {
    updateRow(rowId, (row) =>
      row.lease === null ? row : { ...row, lease: { ...row.lease, [key]: value } },
    );
  }

  function updateVacancyField(
    rowId: string,
    key: keyof InitialVacancyFormValues,
    value: string,
  ): void {
    updateRow(rowId, (row) => ({
      ...row,
      initialVacancy: { ...row.initialVacancy, [key]: value },
    }));
  }

  function updateOverrideField(
    rowId: string,
    key: keyof MarketLeasingFormValues,
    value: string,
  ): void {
    updateRow(rowId, (row) => ({
      ...row,
      marketLeasingOverride: { ...row.marketLeasingOverride, [key]: value },
    }));
  }

  /** Turns the full suite override on or off.
   *
   * Only the flag moves. The override's values are kept while it is off, and
   * `market_rent_psf` is left completely alone -- the contract can carry both at
   * once, and deleting the rent-only override because the full one was switched
   * on would destroy an assumption the analyst still wants when they switch it
   * back off. */
  function toggleOverride(rowId: string): void {
    updateRow(rowId, (row) => ({
      ...row,
      marketLeasingOverrideEnabled: !row.marketLeasingOverrideEnabled,
    }));
  }

  /**
   * Occupied <-> vacant. The control edits the lease, because the lease *is* the
   * status: a suite is occupied exactly when one covers it.
   *
   * **Occupied to vacant destroys a lease**, so a populated one is confirmed
   * first. Vacancy state is not chosen here either: the row keeps whatever
   * treatment it was holding, which is blank for a suite that has never been
   * vacant, and the backend then asks for one by name
   * (`MISSING_INITIAL_VACANCY_TREATMENT`) rather than Anchor picking Hold Vacant
   * or Market Lease-Up on the analyst's behalf.
   *
   * **Vacant to occupied creates an empty lease.** Not a rent, not a term, not a
   * lease type, and emphatically not NNN. The suite's dormant vacancy treatment
   * stays in local state but stops being submitted, because an occupied suite
   * carrying one is refused (`INITIAL_VACANCY_ON_OCCUPIED_SUITE`).
   */
  function toggleOccupancy(rowId: string): void {
    const row = values.rentRoll.find((candidate) => candidate.rowId === rowId);
    if (row === undefined) {
      return;
    }
    if (row.lease !== null) {
      if (leaseHasContent(row.lease)) {
        const name = row.suiteId.trim() === '' ? 'this suite' : `suite ${row.suiteId.trim()}`;
        const tenant = row.lease.tenantName.trim();
        const who = tenant === '' ? 'The lease' : `The lease for ${tenant}`;
        if (
          !window.confirm(
            `Mark ${name} vacant? ${who} will be removed, and its rent, dates and terms discarded.`,
          )
        ) {
          return;
        }
      }
      updateRow(rowId, (candidate) => ({ ...candidate, lease: null }));
      return;
    }
    updateRow(rowId, (candidate) => ({ ...candidate, lease: blankLeaseFormValues() }));
  }

  /** Copies the suite's area into the lease's leased area.
   *
   * An explicit action, never a mirror. D1-D3 require the two to be equal, but
   * copying automatically would hide a rent roll that genuinely disagrees with
   * itself, and would then have to decide what to do when the suite area changes
   * later. The analyst asks, once. */
  function useSuiteArea(rowId: string): void {
    updateRow(rowId, (row) =>
      row.lease === null ? row : { ...row, lease: { ...row.lease, leasedAreaSf: row.suiteAreaSf } },
    );
  }

  return {
    values,
    dealName,
    dealContext,
    currentDealId,
    saveStatus,
    lastSavedAt,
    isDirty,
    activeSection,
    setActiveSection,
    resultsView,
    setResultsView,
    periodView,
    setPeriodView,
    results,
    isAnalyzing,
    isSaving,
    error,
    saveError,
    leaseIssues,
    termsIssues,
    issuesByRow: resolveRowIssues(leaseIssues, submitted).byRow,
    editorRowId,
    openEditor: setEditorRowId,
    closeEditor: () => setEditorRowId(null),
    area: reconcileArea(values),
    addRow,
    deleteRow,
    updateSuiteField,
    updateLeaseField,
    updateVacancyField,
    updateOverrideField,
    toggleOverride,
    toggleOccupancy,
    useSuiteArea,
    onTermsFieldChange,
    onPropertyFieldChange,
    onOperatingFieldChange,
    onMarketFieldChange,
    onDealNameChange: setDealName,
    onDealContextChange,
    buildRequest,
    analyze,
    save,
    open,
    resetToBlank,
    confirmDiscardIfDirty,
  };
}
