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
  buildLeaseLevelFormValues,
  buildLeaseLevelInputsRequest,
  buildLeaseLevelTermsRequest,
  collectBlankScalarIssues,
} from './leaseLevelConvert';
import type { LeaseLevelSectionId } from './components/LeaseLevelWorkspace';
import type { SaveStatus } from './components/DealHeader';
import type {
  LeaseLevelAcquisitionResults,
  LeaseLevelFormValues,
  LeaseLevelInputsRequest,
  LeaseLevelIssue,
  LeaseLevelOperatingFormValues,
  LeaseLevelPropertyFormValues,
  MarketLeasingFormValues,
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

  /** The last successful analysis. Held, not rendered: D5.6 owns the result
   * surfaces, and this gate deliberately renders none of it rather than
   * inventing a presentation nobody has reviewed. */
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

  onTermsFieldChange: (key: keyof AcquisitionTermsFormValues, value: string) => void;
  onPropertyFieldChange: (key: keyof LeaseLevelPropertyFormValues, value: string) => void;
  onOperatingFieldChange: (key: keyof LeaseLevelOperatingFormValues, value: string) => void;
  onMarketFieldChange: (key: keyof MarketLeasingFormValues, value: string) => void;
  onDealNameChange: (value: string) => void;
  onDealContextChange: (value: string) => void;

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
 * Dirty comparison over the scalar assumptions.
 *
 * Scalars only, and deliberately so: D5.5A cannot edit a suite or a lease, so
 * the loaded rows are identical to the saved rows by construction. The two
 * arrays are compared by *identity* -- if `open` put them there and nothing
 * replaced them, they are the same objects. D5.5B, which can edit them, owes
 * the field-by-field array comparison the plan calls for (§10); until then this
 * cannot report a false "saved", because nothing here can change a row.
 */
function isSameSnapshot(a: LeaseLevelSnapshot, b: LeaseLevelSnapshot): boolean {
  if (a.dealName !== b.dealName || a.dealContext !== b.dealContext) {
    return false;
  }
  if (a.values.suites !== b.values.suites || a.values.leases !== b.values.leases) {
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

  const [results, setResults] = useState<LeaseLevelAcquisitionResults | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [leaseIssues, setLeaseIssues] = useState<LeaseLevelIssue[]>([]);
  const [termsIssues, setTermsIssues] = useState<ValidationIssue[]>([]);

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
  function buildRequest(): { terms: AcquisitionTermsRequest; inputs: LeaseLevelInputsRequest } | null {
    const blanks = collectBlankScalarIssues(values);
    if (blanks.leaseIssues.length > 0 || blanks.termsIssues.length > 0) {
      setLeaseIssues(blanks.leaseIssues);
      setTermsIssues(blanks.termsIssues);
      return null;
    }
    return {
      terms: buildLeaseLevelTermsRequest(values.terms),
      inputs: buildLeaseLevelInputsRequest(values),
    };
  }

  const BLANKS_MESSAGE =
    'Some assumptions are still blank. They are marked on the tab that holds them.';

  async function analyze(): Promise<void> {
    setIsAnalyzing(true);
    setError(null);
    setLeaseIssues([]);
    setTermsIssues([]);
    try {
      const request = buildRequest();
      if (request === null) {
        setError(BLANKS_MESSAGE);
        return;
      }
      const analysis = await analyzeLeaseLevelAcquisition(request.terms, request.inputs);
      setResults(analysis);
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
        setSaveError(BLANKS_MESSAGE);
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
    results,
    isAnalyzing,
    isSaving,
    error,
    saveError,
    leaseIssues,
    termsIssues,
    onTermsFieldChange,
    onPropertyFieldChange,
    onOperatingFieldChange,
    onMarketFieldChange,
    onDealNameChange: setDealName,
    onDealContextChange,
    analyze,
    save,
    open,
    resetToBlank,
    confirmDiscardIfDirty,
  };
}
