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
import type { AIAnalysis, ReturnHurdleMetric } from './types';
import {
  ApiError,
  LeaseLevelApiError,
  analyzeLeaseLevelAcquisition,
  createLeaseLevelDeal,
  fetchLeaseLevelAIAnalysis,
  fetchLeaseLevelDealFingerprint,
  getDeal,
  runLeaseLevelOneWaySensitivity,
  runLeaseLevelTwoWaySensitivity,
  updateDealAiSnapshot,
  updateDealOneWaySensitivitySnapshot,
  updateDealTwoWaySensitivitySnapshot,
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
import { BUSINESS_PLAN_INCOMPLETE_MESSAGE, useBusinessPlan } from './useBusinessPlan';
import { blankBusinessPlanDraft, isSameBusinessPlanDraft } from './businessPlan';
import type {
  BusinessPlanDraft,
  BusinessPlanFieldIssue,
  BusinessPlanInput,
} from './businessPlan';
import type { RowIssues, SubmittedRentRoll } from './leaseLevelIssues';
import type { LeaseLevelSectionId } from './components/LeaseLevelWorkspace';
import { BLANK_LADDER_DRAFT } from './leaseLevelSensitivityLadder';
import {
  LEASE_LEVEL_SENSITIVITY_METRICS,
  LEASE_LEVEL_SENSITIVITY_TARGETS,
  candidateToWireValue,
  sensitivityTarget,
} from './leaseLevelSensitivity';
import type {
  LeaseLevelOneWaySensitivitySnapshot,
  LeaseLevelSensitivityTargetId,
  LeaseLevelTwoWaySensitivitySnapshot,
} from './leaseLevelSensitivityTypes';
import type { OneWaySensitivityConfig } from './components/LeaseLevelOneWaySensitivity';
import type { TwoWaySensitivityConfig } from './components/LeaseLevelTwoWaySensitivity';
import type { LeaseLevelSensitivityViewId } from './components/LeaseLevelSensitivityWorkspace';
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

  /** D6.6: this deal's Business Plan as the shared editor shows it, the issues
   * the editor should mark, and the one edit handler -- which joins the same
   * dirty snapshot and the same downstream reset as every other assumption. */
  businessPlan: BusinessPlanDraft;
  businessPlanIssues: BusinessPlanFieldIssue[];
  onBusinessPlanChange: (next: BusinessPlanDraft) => void;

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
  /** D5.8: the AI Analyst's interpretation of `results`, or `null`.
   *
   * Held beside `results` and cleared by the same `resetDownstream`, because it
   * is downstream of exactly the same assumptions. An interpretation of an
   * analysis the analyst has since edited away is worse than no interpretation:
   * it reads as current and is not. There is deliberately no "stale" badge --
   * the same rule `results` follows applies here, so an AI report that is
   * visible is one written about the numbers on screen. */
  aiAnalysis: AIAnalysis | null;
  isGeneratingAiAnalysis: boolean;
  aiAnalysisError: string | null;
  /** D5.8A: true when what `aiAnalysis` holds came back from persistence rather
   * than from a generation in this session.
   *
   * The report is identical either way -- it is the same stored structured
   * response, not a re-run and not a re-render of prose. This flag exists only
   * so the panel can say where it came from, which matters in exactly one
   * place: after a failed regeneration, where the previous successful report is
   * still on screen beside an error explaining that the new one was refused. */
  isAiAnalysisRestored: boolean;
  /** D5.8B: the report on screen describes underwriting assumptions the analyst
   * has since changed.
   *
   * It is kept and shown -- it is real work, and a faithful record of the inputs
   * it ran against -- but it must never read as current, so the panel carries a
   * visible OUT OF DATE notice while this is true. Derived, never stored: it is
   * the same comparison D5.8A used to decide whether to restore a snapshot at
   * all, so putting the assumptions back exactly makes it false again with no
   * re-run and no extra step. */
  isAiAnalysisStale: boolean;
  /** D5.8B: whether the AI Analyst can be asked for a report right now.
   *
   * `false` when the only thing on screen is an out-of-date report and no
   * deterministic analysis of the current assumptions exists -- regenerating
   * then would mean interpreting an analysis nobody has run. The deal has to be
   * analyzed again first, and the panel says so. */
  canGenerateAiAnalysis: boolean;
  /** Requests one AI interpretation of the current analysis.
   *
   * Requires something analytically grounded for these exact assumptions to
   * already exist -- either `results` from an Analyze in this session, or a
   * restored AI report, which is only ever restored when its stored fingerprint
   * still matches the deal's own assumptions. The AI Analyst interprets
   * verified results and never conjures them, so with neither present there is
   * nothing to interpret and the call is refused before it is made. */
  generateAiAnalysis: (
    targetLeveredIrr: number,
    targetEquityMultiple: number,
    targetHeadlineDscr: number,
    returnHurdleMetric: ReturnHurdleMetric,
  ) => Promise<void>;
  /** D5.8A -- the Lease-Level sensitivity workspace's state, lifted here.
   *
   * It lived inside the workspace component until this gate, which is why it
   * disappeared the moment the analyst opened another deal: the component
   * unmounts, and nothing outside it remembered the run. Held here, it is
   * hydrated per deal from persistence and cleared per deal on open, so no
   * result can bleed from one deal to another and none is lost by navigating.
   *
   * The configuration is the analyst's question, not an underwriting
   * assumption: changing it still never marks the deal dirty and never
   * invalidates anything. */
  sensitivity: LeaseLevelSensitivityState;
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
  buildRequest: () => LeaseLevelRequest | null;

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

/**
 * D5.8A -- everything the Lease-Level Risk workspace reads and writes.
 *
 * Deliberately one object rather than a dozen more fields on
 * `LeaseLevelDealState`: the workspace is handed this whole shape and nothing
 * else of the deal's, so it can be read as a unit and cannot reach anything it
 * has no business touching.
 *
 * `oneWayResult`/`twoWayResult` are what the screen should present *now*: the
 * run performed in this session, or -- when the assumptions on screen are still
 * exactly the assumptions that were saved -- the latest successful run restored
 * from persistence. An assumption edit removes both, because an edit makes both
 * stale. Nothing here re-runs anything to produce them.
 */
export interface LeaseLevelSensitivityState {
  view: LeaseLevelSensitivityViewId;
  setView: (view: LeaseLevelSensitivityViewId) => void;

  oneWayConfig: OneWaySensitivityConfig;
  setOneWayConfig: (
    update: (previous: OneWaySensitivityConfig) => OneWaySensitivityConfig,
  ) => void;
  twoWayConfig: TwoWaySensitivityConfig;
  setTwoWayConfig: (
    update: (previous: TwoWaySensitivityConfig) => TwoWaySensitivityConfig,
  ) => void;

  /** The one-way run being presented, or `null`. Never recomputed to produce:
   * either it was run in this session or it was read back from storage. */
  oneWayResult: LeaseLevelOneWaySensitivitySnapshot | null;
  twoWayResult: LeaseLevelTwoWaySensitivitySnapshot | null;
  /** True when the presented run came from persistence rather than from a run
   * in this session. Used only to label it on screen. */
  isOneWayRestored: boolean;
  isTwoWayRestored: boolean;
  /** D5.8B: this run describes underwriting assumptions that have since
   * changed. Kept on screen, marked OUT OF DATE, and false again the moment the
   * assumptions match it -- exactly as for the AI report above, and by the same
   * comparison. Deal Context is deliberately not part of it: a sensitivity run
   * reads none, so editing the stated strategy leaves these results as current
   * as they were. */
  isOneWayStale: boolean;
  isTwoWayStale: boolean;

  oneWayError: string | null;
  twoWayError: string | null;
  isRunning: boolean;
  runOneWay: () => Promise<void>;
  runTwoWay: () => Promise<void>;
}

/** The one message for "a field is still blank, so no request exists to send".
 *
 * Module scope since D5.7, because the sensitivity workspace builds the same
 * request through the same mapper and must say the same thing when it cannot. */
export const LEASE_LEVEL_BLANKS_MESSAGE =
  'Some assumptions are still blank. They are marked on the tab that holds them.';

/** D6.6: everything one Lease-Level request carries -- the terms, the rent-roll
 * inputs and the deal's Business Plan -- built together by `buildRequest`, so
 * no caller can send the deal without its plan. */
export interface LeaseLevelRequest {
  terms: AcquisitionTermsRequest;
  inputs: LeaseLevelInputsRequest;
  businessPlan: BusinessPlanInput;
}

interface LeaseLevelSnapshot {
  dealName: string;
  values: LeaseLevelFormValues;
  /** D6.6: part of the one dirty comparison, like every other assumption. */
  businessPlan: BusinessPlanDraft;
  dealContext: string;
}

/**
 * D5.8B -- the inputs one analytical artifact was produced from.
 *
 * The frontend counterpart of the two fingerprints the backend stores beside a
 * snapshot, in the form this layer actually has: the assumption strings the
 * analyst submitted, and the Deal Context the AI Analyst read. Comparing an
 * artifact against its own provenance is what lets a result outlive the inputs
 * it describes and still say so, rather than being silently dropped or --
 * worse -- silently kept.
 *
 * `dealName` is deliberately absent. It reaches no fingerprint and no
 * calculation, so renaming a deal has never made an analysis stale and must not
 * start now.
 */
interface AnalysisProvenance {
  values: LeaseLevelFormValues;
  /** D6.6: a Business Plan edit moves every analytical artifact out of date,
   * exactly as an assumption edit does -- both backend fingerprints include a
   * non-empty plan. */
  businessPlan: BusinessPlanDraft;
  dealContext: string;
}

/** One analytical artifact, carried with the inputs that produced it. */
interface Produced<T> {
  artifact: T;
  producedFrom: AnalysisProvenance;
}

/** One artifact as the screen should show it.
 *
 * Internal to this hook. The components downstream receive `artifact` and
 * `isStale` as separate props and never see `producedFrom` -- a presentation
 * component has no business holding a copy of the rent roll. */
interface Presented<T> {
  artifact: T;
  /** The inputs it was produced from. Kept so a later write can ask the same
   * question again without re-deriving which slot the artifact came out of. */
  producedFrom: AnalysisProvenance;
  /** The inputs on screen have moved since this was produced. It is still a
   * faithful record of the inputs it ran against -- it is simply not current. */
  isStale: boolean;
  /** It came back from persistence rather than from a run in this session. */
  isRestored: boolean;
}

/** A new blank snapshot on every call, so no two deals share a plan's arrays. */
function blankSnapshot(): LeaseLevelSnapshot {
  return {
    dealName: '',
    values: BLANK_LEASE_LEVEL_FORM_VALUES,
    businessPlan: blankBusinessPlanDraft(),
    dealContext: '',
  };
}

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
  return (
    isSameValues(a.values, b.values) && isSameBusinessPlanDraft(a.businessPlan, b.businessPlan)
  );
}

/**
 * The underwriting half of the comparison above, on its own since D5.8A.
 *
 * Two persisted artifacts go stale on two different triggers, because they
 * depend on two different things -- exactly as the backend's two fingerprints
 * do. A sensitivity run reads no Deal Context, so editing the stated strategy
 * leaves a saved matrix as valid as it was; the AI report interpreted that
 * strategy, so the same edit invalidates it. Comparing the assumptions alone
 * here, and the whole snapshot above, is what lets each follow its own rule
 * instead of both following the stricter one.
 */
function isSameValues(a: LeaseLevelFormValues, b: LeaseLevelFormValues): boolean {
  // D5.5B: the rent roll is editable, so it joins the one dirty-state system
  // rather than getting a flag of its own that could disagree with it.
  if (!isSameRentRoll(a.rentRoll, b.rentRoll)) {
    return false;
  }
  const groups = ['terms', 'property', 'operating', 'marketLeasing'] as const;
  return groups.every((group) => {
    // Keyed off the values actually present rather than a hand-written field
    // list: a field added to any of the four form contracts joins this
    // comparison automatically, so a new assumption cannot be edited without
    // marking the deal dirty.
    const left = Object.entries(a[group]);
    const right = new Map<string, unknown>(Object.entries(b[group]));
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

/** The empty question the Risk workspace opens on. Lifted from
 * `LeaseLevelSensitivityWorkspace` at D5.8A, unchanged: same metric, same
 * targets, no candidate values, and a blank ladder draft. */
const INITIAL_ONE_WAY: OneWaySensitivityConfig = {
  metric: 'levered_irr',
  assumption: 'exit_cap_rate',
  values: [],
  ladder: BLANK_LADDER_DRAFT,
};

const INITIAL_TWO_WAY: TwoWaySensitivityConfig = {
  metric: 'levered_irr',
  rowAssumption: 'exit_cap_rate',
  rowValues: [],
  rowLadder: BLANK_LADDER_DRAFT,
  columnAssumption: 'purchase_price',
  columnValues: [],
  columnLadder: BLANK_LADDER_DRAFT,
};

/** No candidate values yet is a question that has not been asked, not a run
 * with an empty answer. Stated rather than silently submitted. */
const NO_VALUES_MESSAGE =
  'Enter at least one candidate value before running the sensitivity.';

/** What is said when a completed run could not be written back.
 *
 * The result itself is unaffected and stays on screen -- it came from the
 * backend and is exactly as authoritative as it was. What failed is only the
 * saving of it, and the message says that rather than implying the analysis is
 * suspect. */
const SENSITIVITY_CACHE_FAILURE_MESSAGE =
  'Could not save the latest sensitivity automatically. The result is shown but may not persist if you reload.';

const AI_CACHE_FAILURE_MESSAGE =
  'Could not save the latest AI analysis automatically. It is shown but may not persist if you reload.';

const KNOWN_TARGET_IDS = new Set<string>(
  LEASE_LEVEL_SENSITIVITY_TARGETS.map((target) => target.id),
);
const KNOWN_METRIC_IDS = new Set<string>(
  LEASE_LEVEL_SENSITIVITY_METRICS.map((metric) => metric.id),
);

/**
 * Whether a stored configuration still names things this build understands.
 *
 * A snapshot written by a build that supported a target this one does not is
 * treated as unavailable rather than restored into a selector with no matching
 * option. That is the same posture the store takes toward an incompatible
 * schema version: ignore it, never crash on it, and never render a control
 * whose value is not one of its choices.
 */
function isKnownConfiguration(
  metric: string,
  assumptions: readonly string[],
): boolean {
  return (
    KNOWN_METRIC_IDS.has(metric) &&
    assumptions.every((assumption) => KNOWN_TARGET_IDS.has(assumption))
  );
}

function restorableOneWay(
  snapshot: LeaseLevelOneWaySensitivitySnapshot | null | undefined,
): LeaseLevelOneWaySensitivitySnapshot | null {
  if (!snapshot) {
    return null;
  }
  const { metric, assumption } = snapshot.configuration;
  return isKnownConfiguration(metric, [assumption]) ? snapshot : null;
}

function restorableTwoWay(
  snapshot: LeaseLevelTwoWaySensitivitySnapshot | null | undefined,
): LeaseLevelTwoWaySensitivitySnapshot | null {
  if (!snapshot) {
    return null;
  }
  const { metric, row_assumption, column_assumption } = snapshot.configuration;
  return isKnownConfiguration(metric, [row_assumption, column_assumption])
    ? snapshot
    : null;
}

/** The candidate editor, restored to exactly what was submitted.
 *
 * The visible values are the stored strings, in the stored order -- not
 * regenerated, not reformatted, and not reconstructed from the response's wire
 * values. The ladder draft is blank because a ladder is a typing aid that was
 * never part of the run. */
function oneWayConfigFrom(
  snapshot: LeaseLevelOneWaySensitivitySnapshot,
): OneWaySensitivityConfig {
  return {
    metric: snapshot.configuration.metric,
    assumption: snapshot.configuration.assumption,
    values: [...snapshot.configuration.values],
    ladder: BLANK_LADDER_DRAFT,
  };
}

function twoWayConfigFrom(
  snapshot: LeaseLevelTwoWaySensitivitySnapshot,
): TwoWaySensitivityConfig {
  return {
    metric: snapshot.configuration.metric,
    rowAssumption: snapshot.configuration.row_assumption,
    rowValues: [...snapshot.configuration.row_values],
    rowLadder: BLANK_LADDER_DRAFT,
    columnAssumption: snapshot.configuration.column_assumption,
    columnValues: [...snapshot.configuration.column_values],
    columnLadder: BLANK_LADDER_DRAFT,
  };
}

/** Every candidate value for one target, converted by the shipped unit
 * convention, in the analyst's order. Throws `FormValidationError` for a blank
 * or unparseable entry so the caller can report it by name. */
function wireValues(assumption: LeaseLevelSensitivityTargetId, values: string[]): number[] {
  const target = sensitivityTarget(assumption);
  return values.map((value) => candidateToWireValue(target, value));
}

export function useLeaseLevelDeal(options: {
  /** Called after a successful save so the shared Deal Library refreshes --
   * the same callback Quick and Detailed already use. */
  onDealsChanged: () => void;
  /** Called when opening a deal should land the analyst somewhere. Lease-Level
   * always lands on Underwrite: no analysis snapshot is persisted for this mode
   * (decision D5), so Overview would be empty. */
  onOpened: () => void;
  /** D6.6: called when Analyze or Save is stopped by the Business Plan, so the
   * shell can put Underwrite -- where the marked rows are -- on screen. */
  onRevealBusinessPlan: () => void;
}): LeaseLevelDealState {
  const [values, setValues] = useState<LeaseLevelFormValues>(BLANK_LEASE_LEVEL_FORM_VALUES);
  const [dealName, setDealName] = useState('');
  const [dealContext, setDealContext] = useState('');
  const [currentDealId, setCurrentDealId] = useState<string | null>(null);
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);
  const [savedSnapshot, setSavedSnapshot] = useState<LeaseLevelSnapshot>(blankSnapshot);
  // D6.6: the deal's Business Plan, through the one hook all three modes use.
  const businessPlanState = useBusinessPlan();
  const [activeSection, setActiveSection] = useState<LeaseLevelSectionId>('acquisition');
  const [resultsView, setResultsView] = useState<ResultsViewId>('summary');
  const [periodView, setPeriodView] = useState<OperatingPeriodView>('annual');

  const [results, setResults] = useState<LeaseLevelAcquisitionResults | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  // D5.8A -- two sources, one presented value.
  //
  // `live*` is what this session produced, carried with the inputs it was
  // produced from; `restored*` is the latest successful run read back from
  // persistence, which the backend only ever hands back when it still matches
  // the assumptions the deal was SAVED with -- so its provenance IS
  // `savedSnapshot`, and there is nothing extra to record for it.
  //
  // D5.8A presented the live one when there was one and the restored one only
  // while the assumptions on screen were still the saved ones; anything else
  // vanished. D5.8B keeps it on screen and marks it instead -- see
  // `presentedAnalysis` below. Provenance is what makes that possible: a result
  // can now outlive the inputs it describes, so it has to carry them.
  const [liveAiAnalysis, setLiveAiAnalysis] =
    useState<Produced<AIAnalysis> | null>(null);
  const [restoredAiAnalysis, setRestoredAiAnalysis] = useState<AIAnalysis | null>(null);
  const [isGeneratingAiAnalysis, setIsGeneratingAiAnalysis] = useState(false);
  const [aiAnalysisError, setAiAnalysisError] = useState<string | null>(null);

  const [sensitivityView, setSensitivityView] =
    useState<LeaseLevelSensitivityViewId>('one-way');
  const [oneWayConfig, setOneWayConfig] = useState<OneWaySensitivityConfig>(INITIAL_ONE_WAY);
  const [twoWayConfig, setTwoWayConfig] = useState<TwoWaySensitivityConfig>(INITIAL_TWO_WAY);
  const [liveOneWay, setLiveOneWay] =
    useState<Produced<LeaseLevelOneWaySensitivitySnapshot> | null>(null);
  const [liveTwoWay, setLiveTwoWay] =
    useState<Produced<LeaseLevelTwoWaySensitivitySnapshot> | null>(null);
  const [restoredOneWay, setRestoredOneWay] =
    useState<LeaseLevelOneWaySensitivitySnapshot | null>(null);
  const [restoredTwoWay, setRestoredTwoWay] =
    useState<LeaseLevelTwoWaySensitivitySnapshot | null>(null);
  const [oneWayError, setOneWayError] = useState<string | null>(null);
  const [twoWayError, setTwoWayError] = useState<string | null>(null);
  const [isRunningSensitivity, setIsRunningSensitivity] = useState(false);
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

  const isDirty = !isSameSnapshot(
    { dealName, values, businessPlan: businessPlanState.draft, dealContext },
    savedSnapshot,
  );
  const saveStatus: SaveStatus =
    currentDealId === null ? 'unsaved-deal' : isDirty ? 'unsaved-changes' : 'saved';

  // D5.8A -- may a completed artifact be written to the SAVED deal right now?
  //
  // One question per fingerprint, each asked of exactly what its own artifact
  // depends on: `isUnderwritingDirty` is the frontend's read of the backend's
  // financial-input fingerprint, and adding Deal Context to it gives the
  // AI-context fingerprint. Neither is authority -- the backend recomputes both
  // and refuses a write whose provenance it does not already agree with. These
  // two only decide whether it is worth asking, and their only callers are the
  // two persistence guards below.
  //
  // D5.8B: they are deliberately NOT what decides whether the screen calls
  // something out of date. That question is about the inputs an artifact was
  // produced from, which for a live artifact is not `savedSnapshot` at all --
  // see `presentedAnalysis`.
  const isUnderwritingDirty =
    !isSameValues(values, savedSnapshot.values) ||
    !isSameBusinessPlanDraft(businessPlanState.draft, savedSnapshot.businessPlan);
  const isAiDirty = isUnderwritingDirty || dealContext !== savedSnapshot.dealContext;

  /** What the deal's persisted artifacts were produced from.
   *
   * Not an assumption: a snapshot only ever reaches this hook non-`null`
   * because the backend recomputed the deal's fingerprint on read and found it
   * matching, so the stored assumptions -- which are exactly `savedSnapshot` --
   * are the inputs it was produced from. */
  const savedProvenance: AnalysisProvenance = {
    values: savedSnapshot.values,
    businessPlan: savedSnapshot.businessPlan,
    dealContext: savedSnapshot.dealContext,
  };

  /**
   * D5.8B -- what to show, and whether it is current.
   *
   * The live artifact wins when there is one; otherwise the persisted one. What
   * changed at this gate is the second half: an artifact whose inputs have moved
   * is no longer dropped, it is returned with `isStale` set, so the screen can
   * keep real work visible and say plainly that it describes earlier inputs.
   *
   * The staleness test is the same comparison D5.8A already used, asked of the
   * artifact's own provenance instead of always of `savedSnapshot` -- there is
   * no second staleness algorithm here, and the Deal Context distinction the
   * two backend fingerprints draw is preserved exactly: it counts for the AI
   * report and not for a sensitivity run.
   */
  function presentedAnalysis<T>(
    live: Produced<T> | null,
    restored: T | null,
    { includeDealContext }: { includeDealContext: boolean },
  ): Presented<T> | null {
    const producedFrom = live !== null ? live.producedFrom : savedProvenance;
    const artifact = live !== null ? live.artifact : restored;
    if (artifact === null) {
      return null;
    }
    const isStale =
      !isSameValues(producedFrom.values, values) ||
      !isSameBusinessPlanDraft(producedFrom.businessPlan, businessPlanState.draft) ||
      (includeDealContext && producedFrom.dealContext !== dealContext);
    return { artifact, producedFrom, isStale, isRestored: live === null };
  }

  const presentedAi = presentedAnalysis(liveAiAnalysis, restoredAiAnalysis, {
    includeDealContext: true,
  });
  const presentedOneWay = presentedAnalysis(liveOneWay, restoredOneWay, {
    includeDealContext: false,
  });
  const presentedTwoWay = presentedAnalysis(liveTwoWay, restoredTwoWay, {
    includeDealContext: false,
  });

  const aiAnalysis = presentedAi?.artifact ?? null;
  const isAiAnalysisStale = presentedAi?.isStale ?? false;
  const isAiAnalysisRestored = (presentedAi?.isRestored ?? false) && !isAiAnalysisStale;
  const oneWayResult = presentedOneWay?.artifact ?? null;
  const twoWayResult = presentedTwoWay?.artifact ?? null;

  /**
   * D5.8B -- whether the AI Analyst may be asked for a report at all.
   *
   * `results` is a deterministic analysis of the assumptions currently on
   * screen, so with one present the question is always answerable. Without one,
   * a report that is itself current still proves these exact inputs were
   * analyzed (D5.8A's widening) -- but a STALE report proves nothing about
   * them, and regenerating from it would be asking the AI Analyst to interpret
   * an analysis nobody has run. That is the stale-result protection this gate
   * is required to keep, so it is enforced here rather than described in a
   * message.
   */
  const canGenerateAiAnalysis =
    results !== null || (aiAnalysis !== null && !isAiAnalysisStale);

  /** Editing any assumption invalidates the analysis that was run on the old
   * ones, and clears the issues raised against them -- the same rule Quick and
   * Detailed apply. Results are dropped, never recomputed automatically. */
  function resetDownstream() {
    setResults(null);
    // D5.8: the AI report is downstream of the same assumptions the analysis
    // is, so it is dropped by the same rule and at the same moment. Leaving it
    // on screen beside cleared results would be the one genuinely misleading
    // state this workspace could reach -- a narrative about numbers that are no
    // longer there.
    //
    // D5.8A: what is dropped is this session's report, not the SAVED one. The
    // saved snapshot belongs to the assumptions it was produced from and is
    // still valid for them, and deleting it here would destroy valid work over
    // an edit the analyst went on to abandon.
    //
    // D5.8B goes further and drops neither. An AI report and a sensitivity run
    // are completed analytical work; an edit does not make them untrue, it makes
    // them describe earlier inputs. Both stay exactly where they are and are
    // marked `isStale` by `presentedAnalysis`, which compares each against the
    // provenance it carries -- so the analyst keeps the reference and is told,
    // in words, that it is not current. `results` is still dropped: the base
    // deterministic analysis is the thing a fresh AI report would have to be
    // grounded in, and a stale one must not be.
    //
    // What is cleared here is the errors. A refusal raised against a submission
    // the analyst has since edited past is stale in a way a *message* cannot
    // usefully be, and leaving it up would put a failure and a staleness notice
    // on screen describing two different moments.
    setAiAnalysisError(null);
    setOneWayError(null);
    setTwoWayError(null);
    setError(null);
    setLeaseIssues([]);
    setTermsIssues([]);
    setSubmitted(EMPTY_SUBMITTED_RENT_ROLL);
    businessPlanState.clearApiIssues();
  }

  /** D5.8A -- the fingerprint tokens for the request just submitted.
   *
   * Fetched fresh from the exact terms/inputs/Deal Context the work was done
   * under, never cached across calls: the backend stays the sole authority on
   * what a valid fingerprint is, and this only transports the opaque strings it
   * returns.
   */
  /** The inputs on screen at this moment -- what anything produced now was
   * produced from. Captured at the call site rather than derived later, because
   * "later" is exactly when the analyst may have edited them. */
  function currentProvenance(): AnalysisProvenance {
    return { values, businessPlan: businessPlanState.draft, dealContext };
  }

  async function fingerprintFor(request: LeaseLevelRequest) {
    return fetchLeaseLevelDealFingerprint(
      request.terms,
      request.inputs,
      request.businessPlan,
      dealContext.trim() || null,
    );
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

  /** D6.6: a Business Plan edit is an underwriting edit. It marks the deal
   * dirty through the snapshot above and drops the analysis exactly as any
   * other assumption does; persisted results go out of date rather than away. */
  function onBusinessPlanChange(next: BusinessPlanDraft) {
    businessPlanState.change(next);
    resetDownstream();
  }

  /** D6.6: Analyze or Save was stopped by the plan -- put its rows on screen. */
  function revealBusinessPlan() {
    setActiveSection('acquisition');
    options.onRevealBusinessPlan();
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

  /** D6.6: the request, or which of the two things stopped it -- a blank
   * assumption, or the Business Plan -- so each caller can say the right one. */
  function prepareRequest():
    | { ok: true; request: LeaseLevelRequest }
    | { ok: false; reason: 'blanks' | 'business_plan'; message: string } {
    const blanks = collectBlankScalarIssues(values);
    const rowBlanks = collectRentRollBlankIssues(values);
    // D6.6: asked on every attempt, so the plan's own rows are marked even when
    // a blank elsewhere is what stops this request.
    const businessPlan = businessPlanState.prepare();
    if (
      blanks.leaseIssues.length > 0 ||
      blanks.termsIssues.length > 0 ||
      rowBlanks.length > 0
    ) {
      captureSubmitted(null);
      setLeaseIssues([...blanks.leaseIssues, ...rowBlanks]);
      setTermsIssues(blanks.termsIssues);
      return { ok: false, reason: 'blanks', message: LEASE_LEVEL_BLANKS_MESSAGE };
    }
    if (businessPlan === null) {
      return {
        ok: false,
        reason: 'business_plan',
        message: BUSINESS_PLAN_INCOMPLETE_MESSAGE,
      };
    }
    const inputs = buildLeaseLevelInputsRequest(values);
    captureSubmitted(inputs.leases.map((lease) => lease.suite_id));

    return {
      ok: true,
      request: {
        terms: buildLeaseLevelTermsRequest(values.terms),
        inputs,
        businessPlan,
      },
    };
  }

  function buildRequest(): LeaseLevelRequest | null {
    const prepared = prepareRequest();
    return prepared.ok ? prepared.request : null;
  }

  async function analyze(): Promise<void> {
    setIsAnalyzing(true);
    setError(null);
    setLeaseIssues([]);
    setTermsIssues([]);
    let submittedPlan: BusinessPlanInput | null = null;
    try {
      const prepared = prepareRequest();
      if (!prepared.ok) {
        setError(prepared.message);
        if (prepared.reason === 'business_plan') {
          revealBusinessPlan();
        }
        return;
      }
      const { request } = prepared;
      submittedPlan = request.businessPlan;
      const analysis = await analyzeLeaseLevelAcquisition(
        request.terms,
        request.inputs,
        request.businessPlan,
      );
      setResults(analysis);
      // D5.6: Analyze must visibly do something. Landing on Results is what
      // makes a successful run self-evident rather than something the analyst
      // has to go looking for.
      setActiveSection('results');
    } catch (caught) {
      setResults(null);
      setError(recordFailure(caught, 'An unexpected error occurred while analyzing the deal.'));
      if (businessPlanState.recordApiFailure(caught, submittedPlan)) {
        revealBusinessPlan();
      }
    } finally {
      setIsAnalyzing(false);
    }
  }

  /**
   * D5.8 -- one AI interpretation of the analysis currently on screen.
   *
   * Sends the same request body `analyze` sent, so the backend grounds the
   * interpretation in the same deal. It does **not** send `results`: the
   * authoritative analysis is the backend's, and shipping a client-held copy
   * back for the model to read would put a second version of the numbers on
   * the wire.
   *
   * Refused outright when nothing has been analyzed. That guard is what makes
   * "the AI Analyst never invents results" true at this layer rather than only
   * in the prompt.
   */
  async function generateAiAnalysis(
    targetLeveredIrr: number,
    targetEquityMultiple: number,
    targetHeadlineDscr: number,
    returnHurdleMetric: ReturnHurdleMetric,
  ): Promise<void> {
    // D5.8A: a restored report satisfies the guard as well as a fresh analysis
    // does. It is only ever restored when its stored fingerprint still matches
    // the deal's own assumptions, so its presence is itself evidence that these
    // exact inputs were analyzed -- and Regenerate must work on a reopened deal
    // without making the analyst press Analyze again first. The guard still
    // refuses outright when neither exists, which is what keeps "the AI Analyst
    // never invents results" true at this layer and not only in the prompt.
    //
    // D5.8B narrows it back by exactly the case D5.8A could not yet see: a
    // report that is on screen but OUT OF DATE. It evidences an analysis of
    // inputs the analyst has since changed, so it evidences nothing about the
    // inputs a new report would have to describe. `canGenerateAiAnalysis` is
    // that rule, and the shell disables the control on the same value -- but it
    // is enforced here too, because a guard that lives only in a disabled
    // attribute is not a guard.
    if (!canGenerateAiAnalysis) {
      return;
    }
    setIsGeneratingAiAnalysis(true);
    setAiAnalysisError(null);
    try {
      const prepared = prepareRequest();
      if (!prepared.ok) {
        setAiAnalysisError(prepared.message);
        return;
      }
      const { request } = prepared;
      const analysis = await fetchLeaseLevelAIAnalysis(
        request.terms,
        request.inputs,
        request.businessPlan,
        targetLeveredIrr,
        targetEquityMultiple,
        targetHeadlineDscr,
        returnHurdleMetric,
        dealContext.trim() || null,
      );
      setLiveAiAnalysis({ artifact: analysis, producedFrom: currentProvenance() });
      persistAiSnapshot(request, analysis);
    } catch (caught) {
      // D5.8A: a failed regeneration destroys nothing. The previous successful
      // report -- this session's or the saved one -- stays exactly where it was,
      // with the error beside it saying the new one was refused. Clearing it
      // here would lose completed work over a provider outage.
      setAiAnalysisError(
        caught instanceof Error
          ? caught.message
          : 'An unexpected error occurred while generating the AI analysis.',
      );
    } finally {
      setIsGeneratingAiAnalysis(false);
    }
  }

  /**
   * D5.8A -- write one successful AI report back to the deal it describes.
   *
   * Fired without blocking, exactly as Quick and Detailed already do: it never
   * delays what the analyst is looking at, never marks the deal dirty (it
   * touches no assumption, no name, no Deal Context and not `updated_at`), and
   * never requires an explicit Save.
   *
   * Skipped for an unsaved deal, and for one with unsaved assumption or Deal
   * Context edits -- caching a snapshot against assumptions that were never
   * saved would break the invariant that a stored snapshot always matches the
   * stored deal. Those reports are attached by `save` instead, at the moment
   * the assumptions they describe actually become the saved ones.
   */
  function persistAiSnapshot(
    request: LeaseLevelRequest,
    analysis: AIAnalysis,
  ): void {
    const dealId = currentDealId;
    if (dealId === null || isAiDirty) {
      return;
    }
    void (async () => {
      try {
        const fingerprint = await fingerprintFor(request);
        await updateDealAiSnapshot(dealId, analysis, fingerprint.ai_context_fingerprint);
        setRestoredAiAnalysis(analysis);
        setSaveError(null);
      } catch {
        setSaveError(AI_CACHE_FAILURE_MESSAGE);
      }
    })();
  }

  // ===========================================================================
  // D5.8A -- the Lease-Level sensitivity runs
  //
  // Moved here from `LeaseLevelSensitivityWorkspace` unchanged in what they
  // send and what they do with a refusal. What is new is only where the answer
  // goes: into state that belongs to the deal, and -- for a successful run on a
  // saved, unedited deal -- into persistence.
  //
  // Neither computes anything. Candidate values are converted by the shipped
  // unit convention and submitted; the response is stored and shown.
  // ===========================================================================

  /** The message for a failed run.
   *
   * A backend refusal is surfaced as the backend worded it --
   * `SENSITIVITY_TARGET_SHADOWED_BY_SUITE_OVERRIDE`,
   * `NON_POSITIVE_FORWARD_EXIT_NOI`, an unsupported target, a repeated axis
   * target. None of them is converted into `N/A`, a zero, a skipped cell or a
   * partial table. */
  function sensitivityMessageFor(caught: unknown): string {
    if (caught instanceof ApiError || caught instanceof FormValidationError) {
      return caught.message;
    }
    return 'An unexpected error occurred while running the sensitivity.';
  }

  /** Writes one successful sensitivity run back to the deal it belongs to.
   *
   * Same contract as `persistAiSnapshot`: non-blocking, dirty-guarded, and
   * touching nothing but its own stored row -- so persisting a one-way run can
   * never disturb the saved two-way matrix, and vice versa.
   *
   * Called only from the success path of a run. A validation failure, a
   * shadowed target, a `NON_POSITIVE_FORWARD_EXIT_NOI` refusal or a transport
   * error never reaches here, so a refused run cannot replace the last
   * successful snapshot -- that is structural, not a rule to remember.
   */
  function persistSensitivitySnapshot(
    request: LeaseLevelRequest,
    write: (dealId: string, fingerprint: string) => Promise<unknown>,
    remember: () => void,
  ): void {
    const dealId = currentDealId;
    if (dealId === null || isUnderwritingDirty) {
      return;
    }
    void (async () => {
      try {
        const fingerprint = await fingerprintFor(request);
        await write(dealId, fingerprint.financial_input_fingerprint);
        remember();
        setSaveError(null);
      } catch {
        setSaveError(SENSITIVITY_CACHE_FAILURE_MESSAGE);
      }
    })();
  }

  async function runOneWay(): Promise<void> {
    setOneWayError(null);
    if (oneWayConfig.values.length === 0) {
      setOneWayError(NO_VALUES_MESSAGE);
      return;
    }
    setIsRunningSensitivity(true);
    try {
      const prepared = prepareRequest();
      if (!prepared.ok) {
        setOneWayError(prepared.message);
        return;
      }
      const { request } = prepared;
      // The configuration is captured here, from what is actually being
      // submitted, so the snapshot below can never pair one run's question with
      // another run's answer.
      const configuration = {
        metric: oneWayConfig.metric,
        assumption: oneWayConfig.assumption,
        values: [...oneWayConfig.values],
      };
      const result = await runLeaseLevelOneWaySensitivity(
        request.terms,
        request.inputs,
        request.businessPlan,
        {
        assumption: configuration.assumption,
        values: wireValues(configuration.assumption, configuration.values),
        metric: configuration.metric,
      });
      const snapshot: LeaseLevelOneWaySensitivitySnapshot = { configuration, result };
      setLiveOneWay({ artifact: snapshot, producedFrom: currentProvenance() });
      persistSensitivitySnapshot(
        request,
        (dealId, fingerprint) =>
          updateDealOneWaySensitivitySnapshot(dealId, snapshot, fingerprint),
        () => setRestoredOneWay(snapshot),
      );
    } catch (caught) {
      // D5.7 cleared this session's table here, so a refusal was never left on
      // screen beside a table that appeared to answer it. D5.8B keeps the table
      // and separates the two facts instead: the refusal is its own message, the
      // previous run is labelled as the previous run, and if the inputs have
      // moved it also carries the out-of-date notice. Three distinct states,
      // three distinct pieces of text -- collapsing them into one was the only
      // thing the old clearing actually prevented, and it cost the analyst a
      // completed run every time a re-run was refused.
      //
      // Nothing about the kept result changes: it keeps the provenance it was
      // produced under, so it is never relabelled as an answer to the run that
      // just failed.
      setOneWayError(sensitivityMessageFor(caught));
    } finally {
      setIsRunningSensitivity(false);
    }
  }

  async function runTwoWay(): Promise<void> {
    setTwoWayError(null);
    if (twoWayConfig.rowValues.length === 0 || twoWayConfig.columnValues.length === 0) {
      setTwoWayError(NO_VALUES_MESSAGE);
      return;
    }
    setIsRunningSensitivity(true);
    try {
      const prepared = prepareRequest();
      if (!prepared.ok) {
        setTwoWayError(prepared.message);
        return;
      }
      const { request } = prepared;
      const configuration = {
        metric: twoWayConfig.metric,
        row_assumption: twoWayConfig.rowAssumption,
        row_values: [...twoWayConfig.rowValues],
        column_assumption: twoWayConfig.columnAssumption,
        column_values: [...twoWayConfig.columnValues],
      };
      const result = await runLeaseLevelTwoWaySensitivity(
        request.terms,
        request.inputs,
        request.businessPlan,
        {
        row_assumption: configuration.row_assumption,
        row_values: wireValues(configuration.row_assumption, configuration.row_values),
        column_assumption: configuration.column_assumption,
        column_values: wireValues(configuration.column_assumption, configuration.column_values),
        metric: configuration.metric,
      });
      const snapshot: LeaseLevelTwoWaySensitivitySnapshot = { configuration, result };
      setLiveTwoWay({ artifact: snapshot, producedFrom: currentProvenance() });
      persistSensitivitySnapshot(
        request,
        (dealId, fingerprint) =>
          updateDealTwoWaySensitivitySnapshot(dealId, snapshot, fingerprint),
        () => setRestoredTwoWay(snapshot),
      );
    } catch (caught) {
      // See `runOneWay` above: the matrix stays, the refusal is its own
      // message, and neither is dressed up as the other.
      setTwoWayError(sensitivityMessageFor(caught));
    } finally {
      setIsRunningSensitivity(false);
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
    let submittedPlan: BusinessPlanInput | null = null;
    try {
      const prepared = prepareRequest();
      if (!prepared.ok) {
        setSaveError(prepared.message);
        if (prepared.reason === 'business_plan') {
          revealBusinessPlan();
        }
        return;
      }
      // D6.6: the plan travels with every save, including one that only
      // renamed the deal -- an absent plan would be read as an empty one.
      const { terms, inputs, businessPlan } = prepared.request;
      submittedPlan = businessPlan;
      const name = dealName.trim() || 'Untitled Deal';
      const context = dealContext.trim() || null;
      const deal = currentDealId
        ? await updateLeaseLevelDeal(currentDealId, name, terms, inputs, businessPlan, context)
        : await createLeaseLevelDeal(name, terms, inputs, businessPlan, context);
      setCurrentDealId(deal.id);
      setDealName(deal.name);
      setDealContext(deal.deal_context ?? '');
      setLastSavedAt(deal.updated_at);
      setSavedSnapshot({
        dealName: deal.name,
        values,
        businessPlan: businessPlanState.draft,
        dealContext: deal.deal_context ?? '',
      });
      // D5.8A -- attach whatever analytical work is currently on screen to the
      // deal that has just become its saved form.
      //
      // This is the counterpart of the background refresh above, for the two
      // cases that one deliberately skips: the first Save of a deal that was
      // analyzed before it had an id, and a Save that turns edited assumptions
      // into saved ones. In both, the results on screen were produced from
      // exactly the request just written, so the fingerprint taken from that
      // same request is the provenance the backend will independently agree
      // with. Awaited rather than fired, because Save is the moment the analyst
      // is told their work is stored.
      await attachSnapshotsAfterSave(deal.id, { terms, inputs, businessPlan }, context);
      options.onDealsChanged();
    } catch (caught) {
      setSaveError(recordFailure(caught, 'An unexpected error occurred while saving the deal.'));
      if (businessPlanState.recordApiFailure(caught, submittedPlan)) {
        revealBusinessPlan();
      }
    } finally {
      setIsSaving(false);
    }
  }

  /** Writes the presented AI report and sensitivity runs onto the freshly
   * saved deal, each through its own provenance-validated endpoint.
   *
   * Each write is independent: a report that fails to attach does not stop the
   * matrices from attaching, and none of them can disturb another. A failure
   * here is reported through the header's save message and never as a failed
   * Save -- the assumptions are saved; it is the derived snapshot that is not.
   *
   * **Only a CURRENT artifact is attached (D5.8B).** Saving edited assumptions
   * is the one moment an out-of-date result could be certified against inputs it
   * was never produced from, because Save is what makes those inputs the deal's
   * own. A stale artifact is therefore not written, and its `restored` slot is
   * cleared -- the backend's read-time fingerprint check would stop serving it
   * from this point anyway, and leaving it in that slot would let the next
   * render read its provenance as the freshly-saved assumptions and call it
   * current. It stays on screen through its `live` slot, out-of-date notice
   * intact, because it is still the analyst's work.
   */
  async function attachSnapshotsAfterSave(
    dealId: string,
    request: LeaseLevelRequest,
    context: string | null,
  ): Promise<void> {
    // Whatever is on screen goes on being on screen, held as this session's own
    // result with the provenance it was produced under -- so a Save neither
    // loses a stale reference nor promotes one to current.
    if (presentedAi !== null) {
      setLiveAiAnalysis(presentedAi);
    }
    if (presentedOneWay !== null) {
      setLiveOneWay(presentedOneWay);
    }
    if (presentedTwoWay !== null) {
      setLiveTwoWay(presentedTwoWay);
    }

    const attachAi = presentedAi !== null && !presentedAi.isStale;
    const attachOneWay = presentedOneWay !== null && !presentedOneWay.isStale;
    const attachTwoWay = presentedTwoWay !== null && !presentedTwoWay.isStale;

    if (presentedAi !== null && presentedAi.isStale) {
      setRestoredAiAnalysis(null);
    }
    if (presentedOneWay !== null && presentedOneWay.isStale) {
      setRestoredOneWay(null);
    }
    if (presentedTwoWay !== null && presentedTwoWay.isStale) {
      setRestoredTwoWay(null);
    }

    if (!attachAi && !attachOneWay && !attachTwoWay) {
      return;
    }
    try {
      const fingerprint = await fetchLeaseLevelDealFingerprint(
        request.terms,
        request.inputs,
        request.businessPlan,
        context,
      );
      if (attachAi && presentedAi !== null) {
        await updateDealAiSnapshot(
          dealId,
          presentedAi.artifact,
          fingerprint.ai_context_fingerprint,
        );
        setRestoredAiAnalysis(presentedAi.artifact);
      }
      if (attachOneWay && presentedOneWay !== null) {
        await updateDealOneWaySensitivitySnapshot(
          dealId,
          presentedOneWay.artifact,
          fingerprint.financial_input_fingerprint,
        );
        setRestoredOneWay(presentedOneWay.artifact);
      }
      if (attachTwoWay && presentedTwoWay !== null) {
        await updateDealTwoWaySensitivitySnapshot(
          dealId,
          presentedTwoWay.artifact,
          fingerprint.financial_input_fingerprint,
        );
        setRestoredTwoWay(presentedTwoWay.artifact);
      }
    } catch {
      setSaveError(SENSITIVITY_CACHE_FAILURE_MESSAGE);
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
    // D6.6: the plan exactly as stored -- its item IDs, values and row order.
    const openedPlan = businessPlanState.load(deal.business_plan);
    setValues(opened);
    setDealName(deal.name);
    setDealContext(deal.deal_context ?? '');
    setCurrentDealId(deal.id);
    setLastSavedAt(deal.updated_at);
    setSavedSnapshot({
      dealName: deal.name,
      values: opened,
      businessPlan: openedPlan,
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
    hydrateDerivedAnalysis(deal);
  }

  /**
   * D5.8A -- the derived analytical state of the deal being opened, and only
   * of that deal.
   *
   * Every slot is written on every open, including to `null`: that is what
   * makes cross-deal bleed impossible. Opening a deal with no saved AI report
   * does not leave the previous deal's report on screen, because this clears it
   * rather than skipping over it.
   *
   * The backend has already checked provenance before any of this arrives -- a
   * snapshot whose stored fingerprint no longer matches the deal's own
   * assumptions is returned as `null`, never as a result -- so nothing here
   * decides whether a snapshot is current. What it does decide is whether this
   * build can render it: a configuration naming a target or metric this build
   * does not know is treated as unavailable rather than restored into a control
   * that has no such option.
   *
   * Nothing is re-run. The tables that appear are the stored responses.
   */
  function hydrateDerivedAnalysis(deal: Deal): void {
    setLiveAiAnalysis(null);
    setAiAnalysisError(null);
    setRestoredAiAnalysis(deal.ai_snapshot);

    const oneWay = restorableOneWay(deal.one_way_sensitivity_snapshot);
    const twoWay = restorableTwoWay(deal.two_way_sensitivity_snapshot);
    setLiveOneWay(null);
    setLiveTwoWay(null);
    setRestoredOneWay(oneWay);
    setRestoredTwoWay(twoWay);
    setOneWayError(null);
    setTwoWayError(null);
    setSensitivityView('one-way');
    // The candidate editor comes back as it was submitted, or blank when there
    // is nothing to come back to -- never as the previous deal's question.
    setOneWayConfig(oneWay === null ? INITIAL_ONE_WAY : oneWayConfigFrom(oneWay));
    setTwoWayConfig(twoWay === null ? INITIAL_TWO_WAY : twoWayConfigFrom(twoWay));
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
    // D6.6: a new deal has no Business Plan -- no rows, nothing assumed.
    businessPlanState.reset();
    setDealName('');
    setDealContext('');
    setCurrentDealId(null);
    setLastSavedAt(null);
    setSavedSnapshot(blankSnapshot());
    setActiveSection('acquisition');
    setEditorRowId(null);
    setSubmitted(EMPTY_SUBMITTED_RENT_ROLL);
    setResults(null);
    setError(null);
    setSaveError(null);
    setLeaseIssues([]);
    setTermsIssues([]);
    // D5.8A: a new deal starts with no analytical state at all -- the same
    // clearing an open performs, with nothing to hydrate.
    setLiveAiAnalysis(null);
    setRestoredAiAnalysis(null);
    setAiAnalysisError(null);
    setLiveOneWay(null);
    setLiveTwoWay(null);
    setRestoredOneWay(null);
    setRestoredTwoWay(null);
    setOneWayError(null);
    setTwoWayError(null);
    setSensitivityView('one-way');
    setOneWayConfig(INITIAL_ONE_WAY);
    setTwoWayConfig(INITIAL_TWO_WAY);
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
    businessPlan: businessPlanState.draft,
    businessPlanIssues: businessPlanState.issues,
    onBusinessPlanChange,
    activeSection,
    setActiveSection,
    resultsView,
    setResultsView,
    periodView,
    setPeriodView,
    results,
    isAnalyzing,
    aiAnalysis,
    isGeneratingAiAnalysis,
    aiAnalysisError,
    isAiAnalysisRestored,
    isAiAnalysisStale,
    canGenerateAiAnalysis,
    generateAiAnalysis,
    sensitivity: {
      view: sensitivityView,
      setView: setSensitivityView,
      oneWayConfig,
      setOneWayConfig,
      twoWayConfig,
      setTwoWayConfig,
      oneWayResult,
      twoWayResult,
      isOneWayRestored: (presentedOneWay?.isRestored ?? false) && !presentedOneWay!.isStale,
      isTwoWayRestored: (presentedTwoWay?.isRestored ?? false) && !presentedTwoWay!.isStale,
      isOneWayStale: presentedOneWay?.isStale ?? false,
      isTwoWayStale: presentedTwoWay?.isStale ?? false,
      oneWayError,
      twoWayError,
      isRunning: isRunningSensitivity,
      runOneWay,
      runTwoWay,
    },
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
