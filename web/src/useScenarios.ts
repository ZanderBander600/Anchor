/**
 * Phase 7 Gate P7.3 -- the Scenario state of one open Deal.
 *
 * P7 state lives in a dedicated hook, never in `App.tsx`, following
 * `useLeaseLevelDeal` and `useBusinessPlan`. The hook owns:
 * - the Deal's saved Scenarios;
 * - the target catalog for the Deal's operating mode;
 * - the Scenario editor and its feedback;
 * - deletion;
 * - the Scenario Comparison.
 *
 * **One Deal per mount.** The owner remounts the hook when the open Deal changes
 * (`ScenarioWorkspace` is keyed by mode and Deal id), so nothing from one Deal can
 * reach another by construction.
 *
 * **Opt-in, and read-only until the analyst acts.** Nothing is requested until
 * the Risk workspace is on screen, and a read never creates anything. The first
 * Scenario the analyst saves is what materializes the Deal's hidden Investment,
 * through the P7.2 route that owns that. A Deal that has never been saved has no
 * Scenarios: it gets no request, no temporary id and no local stand-in.
 *
 * **The saved Deal is the base.** Persisted Scenarios resolve against the
 * Deal's *saved* inputs. While the base underwriting has unsaved edits, nothing
 * here runs, and Scenario edits wait: running would compare persisted Scenario
 * results with a Base the analyst is no longer looking at.
 *
 * **Every number comes from the backend.**
 * - Base is the saved Deal's ordinary analysis: `GET /deals/{id}`, then the
 *   mode's existing `POST /analyze`.
 * - Each Scenario column is the P7.2 Scenario analysis.
 * - Each column settles on its own. One refusal never blanks another column,
 *   and the hook does no arithmetic on any result.
 *
 * **Out of date is deterministic.** A comparison records a token of what it ran
 * against:
 * - the Deal;
 * - the save it was run on;
 * - each Scenario's id and overrides.
 * It is current only while that token still matches and the base is not dirty.
 * A rename or a new description leaves the token unchanged, so the column label
 * updates without a re-run.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  analyzeAcquisition,
  analyzeDetailedAcquisition,
  analyzeInvestmentScenario,
  analyzeLeaseLevelAcquisition,
  ApiError,
  createDealScenario,
  deleteInvestmentScenario,
  fetchScenarioTargetCatalog,
  getDeal,
  listDealScenarios,
  ScenarioApiError,
  updateInvestmentScenario,
} from './api';
import { FormValidationError } from './convert';
import { assertNeverMode } from './operatingMode';
import {
  scenarioTargetLabel,
  scenarioValueToText,
  scenarioValueToWire,
  sharesValueScale,
} from './scenarioCatalog';
import { acquisitionResultsOf } from './scenarioComparison';
import type { ComparisonCell, ScenarioComparison } from './scenarioComparison';
import type {
  InvestmentScenario,
  ScenarioDraft,
  ScenarioOperation,
  ScenarioOverride,
  ScenarioTargetEntry,
} from './scenarioTypes';
import type { AcquisitionResults, Deal, OperatingMode } from './types';

export interface UseScenariosOptions {
  operatingMode: OperatingMode;
  /** The open Deal's saved id, or `null` for a Deal that has never been saved. */
  dealId: string | null;
  /** Whether the base underwriting has unsaved edits. */
  isDirty: boolean;
  /** The Deal's `updated_at` as of its last Save or Open. A new save moves it. */
  savedAt: string | null;
  /** Whether the Risk workspace is on screen. Nothing is requested before it is. */
  isActive: boolean;
}

/** One override row in the editor, as typed. `key` identifies the row for
 * React only and never reaches the backend. */
export interface ScenarioEditorRow {
  key: string;
  target: string;
  operation: ScenarioOperation | '';
  value: string;
}

/** The editor's working copy. `scenarioId` is `null` for a new Scenario: the
 * backend assigns the id when it is saved, never the browser. */
export interface ScenarioEditorDraft {
  scenarioId: string | null;
  name: string;
  description: string;
  rows: ScenarioEditorRow[];
}

/** Why a save did not happen. `general` holds what no row owns; `byRow` holds
 * what one override row owns, keyed by the row's key. Backend messages are kept
 * in the backend's own words. */
export interface ScenarioEditorFeedback {
  message: string;
  general: string[];
  byRow: Record<string, string[]>;
}

type ListState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; investmentId: string | null; scenarios: InvestmentScenario[] }
  | { status: 'error'; message: string };

type CatalogState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; targets: ScenarioTargetEntry[] }
  | { status: 'error'; message: string };

export type ScenarioListStatus = 'unsaved' | 'idle' | 'loading' | 'ready' | 'error';

export interface ScenariosState {
  dealId: string | null;
  isDirty: boolean;
  listStatus: ScenarioListStatus;
  loadError: string | null;
  retryLoad: () => void;
  scenarios: InvestmentScenario[];
  /** The registry's targets for this Deal's operating mode. */
  targets: ScenarioTargetEntry[];
  catalogStatus: CatalogState['status'];
  catalogError: string | null;
  retryCatalog: () => void;
  /** Saved, clean and loaded: the only state a Scenario may be changed in. */
  canEdit: boolean;

  editor: ScenarioEditorDraft | null;
  feedback: ScenarioEditorFeedback | null;
  isSaving: boolean;
  openNew: () => void;
  openEdit: (scenarioId: string) => void;
  cancelEdit: () => void;
  setEditorName: (name: string) => void;
  setEditorDescription: (description: string) => void;
  addRow: () => void;
  removeRow: (key: string) => void;
  setRowTarget: (key: string, target: string) => void;
  setRowOperation: (key: string, operation: ScenarioOperation | '') => void;
  setRowValue: (key: string, value: string) => void;
  saveEditor: () => Promise<void>;

  pendingDeleteId: string | null;
  isDeleting: boolean;
  deleteError: string | null;
  requestDelete: (scenarioId: string) => void;
  cancelDelete: () => void;
  confirmDelete: () => Promise<void>;

  comparison: ScenarioComparison | null;
  /** The comparison was run against exactly the saved state now on screen. */
  isComparisonCurrent: boolean;
  isRunning: boolean;
  canRun: boolean;
  runComparison: () => Promise<void>;
  retryBase: () => Promise<void>;
  retryScenario: (scenarioId: string) => Promise<void>;
}

const LOADING: ComparisonCell = { status: 'loading' };
const NO_SCENARIOS: InvestmentScenario[] = [];
const NO_TARGETS: ScenarioTargetEntry[] = [];

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'The request could not be completed.';
}

/** The saved Deal's ordinary analysis, through the mode's existing `/analyze`
 * client function, on exactly the inputs and Business Plan the Deal holds. */
async function analyzeSavedDeal(deal: Deal): Promise<AcquisitionResults> {
  switch (deal.operating_mode) {
    case 'quick':
      if (deal.inputs === null) {
        throw new ApiError('The saved deal has no Quick assumptions to analyze.');
      }
      return analyzeAcquisition(deal.inputs, deal.business_plan);
    case 'detailed':
      if (deal.terms === null || deal.detailed_operating_inputs === null) {
        throw new ApiError('The saved deal has no Detailed assumptions to analyze.');
      }
      return (
        await analyzeDetailedAcquisition(deal.terms, deal.detailed_operating_inputs, deal.business_plan)
      ).results;
    case 'lease_level':
      if (
        deal.terms === null ||
        deal.property_inputs === null ||
        deal.operating_inputs === null ||
        deal.market_leasing === null ||
        deal.suites === null ||
        deal.leases === null
      ) {
        throw new ApiError('The saved deal has no Lease-Level assumptions to analyze.');
      }
      return (
        await analyzeLeaseLevelAcquisition(
          deal.terms,
          {
            property_inputs: deal.property_inputs,
            operating_inputs: deal.operating_inputs,
            market_leasing: deal.market_leasing,
            suites: deal.suites,
            leases: deal.leases,
          },
          deal.business_plan,
        )
      ).results;
    default:
      return assertNeverMode(deal.operating_mode);
  }
}

async function analyzeBaseCell(dealId: string): Promise<ComparisonCell> {
  try {
    const deal = await getDeal(dealId);
    return { status: 'result', results: await analyzeSavedDeal(deal), cacheStatus: null };
  } catch (error) {
    return { status: 'error', message: messageOf(error) };
  }
}

/** A 422 is the backend judging the variant invalid, reported with its
 * reasons. Anything else is a request failure, reported as one. */
async function analyzeScenarioCell(record: InvestmentScenario): Promise<ComparisonCell> {
  try {
    const analysis = await analyzeInvestmentScenario(
      record.investment_id,
      record.scenario.scenario_id,
    );
    return {
      status: 'result',
      results: acquisitionResultsOf(analysis),
      cacheStatus: analysis.cache_status,
    };
  } catch (error) {
    if (error instanceof ScenarioApiError && error.status === 422) {
      return { status: 'invalid', reasons: error.reasons.length > 0 ? error.reasons : [error.message] };
    }
    return { status: 'error', message: messageOf(error) };
  }
}

/** The editor's rows as a Scenario body, or the presence and parsing problems
 * that stop it being sent. Presence and parsing only: every rule about what a
 * Scenario may say is the backend's. */
function buildDraft(
  editor: ScenarioEditorDraft,
  unitId: string,
): { draft: ScenarioDraft } | { feedback: ScenarioEditorFeedback } {
  const general: string[] = [];
  const byRow: Record<string, string[]> = {};
  if (editor.name.trim() === '') {
    general.push('Enter a scenario name.');
  }
  const overrides: ScenarioOverride[] = [];
  for (const row of editor.rows) {
    if (row.target === '') {
      byRow[row.key] = ['Choose an assumption.'];
      continue;
    }
    if (row.operation === '') {
      byRow[row.key] = ['Choose an operation.'];
      continue;
    }
    try {
      overrides.push({
        unit_id: unitId,
        target: row.target,
        operation: row.operation,
        value: scenarioValueToWire(
          row.target,
          row.operation,
          row.value,
          `${scenarioTargetLabel(row.target)} value`,
        ),
      });
    } catch (error) {
      if (!(error instanceof FormValidationError)) {
        throw error;
      }
      byRow[row.key] = [error.message];
    }
  }
  if (general.length > 0 || Object.keys(byRow).length > 0) {
    return {
      feedback: { message: 'Complete the highlighted fields before saving.', general, byRow },
    };
  }
  return {
    draft: {
      name: editor.name,
      description: editor.description.trim() === '' ? null : editor.description,
      overrides,
    },
  };
}

/** A refused save, with each P7.1 issue placed on the row whose target it
 * names. Issues no row owns are listed with the editor. */
function feedbackFor(error: unknown, editor: ScenarioEditorDraft): ScenarioEditorFeedback {
  if (!(error instanceof ScenarioApiError)) {
    return { message: messageOf(error), general: [], byRow: {} };
  }
  const general: string[] = [];
  const byRow: Record<string, string[]> = {};
  for (const issue of error.scenarioIssues) {
    const row =
      issue.target === null ? undefined : editor.rows.find((candidate) => candidate.target === issue.target);
    if (row === undefined) {
      general.push(issue.message);
    } else {
      (byRow[row.key] ??= []).push(issue.message);
    }
  }
  for (const issue of [...error.leaseIssues, ...error.issues]) {
    general.push(issue.message);
  }
  if (error.scenarioIssues.length === 0 && general.length === 0) {
    general.push(...error.reasons);
  }
  return {
    message:
      error.status === 422
        ? 'The scenario was not saved. The backend refused it for these reasons:'
        : 'The scenario was not saved.',
    general,
    byRow,
  };
}

/** Reads the Deal's Scenarios. State is set only when the request settles,
 * never synchronously from an effect. */
function loadList(dealId: string, setList: (state: ListState) => void): void {
  listDealScenarios(dealId).then(
    (response) =>
      setList({
        status: 'ready',
        investmentId: response.investment_id,
        scenarios: response.scenarios,
      }),
    (error: unknown) => setList({ status: 'error', message: messageOf(error) }),
  );
}

/** Reads the registry's targets for one operating mode. */
function loadCatalog(operatingMode: OperatingMode, setCatalog: (state: CatalogState) => void): void {
  fetchScenarioTargetCatalog().then(
    (response) => setCatalog({ status: 'ready', targets: response[operatingMode] ?? NO_TARGETS }),
    (error: unknown) => setCatalog({ status: 'error', message: messageOf(error) }),
  );
}

export function useScenarios({
  operatingMode,
  dealId,
  isDirty,
  savedAt,
  isActive,
}: UseScenariosOptions): ScenariosState {
  const [list, setList] = useState<ListState>({ status: 'idle' });
  const [catalog, setCatalog] = useState<CatalogState>({ status: 'idle' });
  const [editor, setEditor] = useState<ScenarioEditorDraft | null>(null);
  const [feedback, setFeedback] = useState<ScenarioEditorFeedback | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [comparison, setComparison] = useState<ScenarioComparison | null>(null);
  /** Identifies the latest run, so a slower earlier run can never write into
   * a later one. Compared by identity only. */
  const activeRun = useRef<object | null>(null);
  /** Editor row keys: a per-mount sequence for React's reconciliation only.
   * Never an id, never sent: `businessPlan.ts` stays the one place the app
   * mints an identifier. */
  const rowSequence = useRef(0);

  function nextRowKey(): string {
    rowSequence.current += 1;
    return `override-row-${rowSequence.current}`;
  }

  function blankRow(): ScenarioEditorRow {
    return { key: nextRowKey(), target: '', operation: '', value: '' };
  }

  /** Each read is requested once per mount; a retry asks again explicitly. */
  const listRequested = useRef(false);
  const catalogRequested = useRef(false);

  useEffect(() => {
    if (!isActive || dealId === null || listRequested.current) {
      return;
    }
    listRequested.current = true;
    loadList(dealId, setList);
  }, [isActive, dealId]);

  useEffect(() => {
    if (!isActive || dealId === null || catalogRequested.current) {
      return;
    }
    catalogRequested.current = true;
    loadCatalog(operatingMode, setCatalog);
  }, [isActive, dealId, operatingMode]);

  const scenarios = list.status === 'ready' ? list.scenarios : NO_SCENARIOS;
  const targets = catalog.status === 'ready' ? catalog.targets : NO_TARGETS;
  const canEdit = dealId !== null && !isDirty && list.status === 'ready';

  const token = useMemo(
    () =>
      JSON.stringify([
        dealId,
        savedAt,
        scenarios.map((record) => [record.scenario.scenario_id, record.scenario.overrides]),
      ]),
    [dealId, savedAt, scenarios],
  );
  const isRunning =
    comparison !== null &&
    (comparison.base.status === 'loading' ||
      Object.values(comparison.scenarios).some((cell) => cell.status === 'loading'));
  const isComparisonCurrent = comparison !== null && comparison.token === token && !isDirty;
  const canRun = canEdit && scenarios.length > 0 && !isRunning;

  function updateRow(key: string, update: (row: ScenarioEditorRow) => ScenarioEditorRow) {
    setEditor((current) =>
      current === null
        ? current
        : { ...current, rows: current.rows.map((row) => (row.key === key ? update(row) : row)) },
    );
  }

  function allowedOperations(target: string): ScenarioOperation[] {
    return targets.find((entry) => entry.target === target)?.allowed_operations ?? [];
  }

  async function saveEditor() {
    if (editor === null || dealId === null || !canEdit || isSaving) {
      return;
    }
    const built = buildDraft(editor, dealId);
    if ('feedback' in built) {
      setFeedback(built.feedback);
      return;
    }
    const existing =
      editor.scenarioId === null
        ? null
        : scenarios.find((record) => record.scenario.scenario_id === editor.scenarioId);
    if (existing === undefined) {
      setFeedback({
        message: 'This scenario no longer exists. Cancel and reload the scenarios.',
        general: [],
        byRow: {},
      });
      return;
    }
    setIsSaving(true);
    setFeedback(null);
    try {
      const saved =
        existing === null
          ? await createDealScenario(dealId, built.draft)
          : await updateInvestmentScenario(
              existing.investment_id,
              existing.scenario.scenario_id,
              built.draft,
            );
      setList((current) =>
        current.status !== 'ready'
          ? current
          : {
              status: 'ready',
              investmentId: saved.investment_id,
              scenarios:
                existing === null
                  ? [...current.scenarios, saved]
                  : current.scenarios.map((record) =>
                      record.scenario.scenario_id === saved.scenario.scenario_id ? saved : record,
                    ),
            },
      );
      setEditor(null);
    } catch (error) {
      // The editor keeps every value the analyst typed.
      setFeedback(feedbackFor(error, editor));
    } finally {
      setIsSaving(false);
    }
  }

  async function confirmDelete() {
    const record = scenarios.find((candidate) => candidate.scenario.scenario_id === pendingDeleteId);
    if (record === undefined || !canEdit || isDeleting) {
      return;
    }
    setIsDeleting(true);
    setDeleteError(null);
    try {
      await deleteInvestmentScenario(record.investment_id, record.scenario.scenario_id);
      const remaining = scenarios.filter((candidate) => candidate !== record);
      // The last Scenario's deletion also removed the hidden Investment
      // (P7.2): the Deal is a plain Deal again, with nothing to compare.
      setList((current) =>
        current.status !== 'ready'
          ? current
          : {
              status: 'ready',
              investmentId: remaining.length === 0 ? null : current.investmentId,
              scenarios: current.scenarios.filter((candidate) => candidate !== record),
            },
      );
      if (remaining.length === 0) {
        activeRun.current = null;
        setComparison(null);
      }
      if (editor?.scenarioId === record.scenario.scenario_id) {
        setEditor(null);
        setFeedback(null);
      }
      setPendingDeleteId(null);
    } catch (error) {
      setDeleteError(messageOf(error));
    } finally {
      setIsDeleting(false);
    }
  }

  async function runComparison() {
    if (!canRun || dealId === null) {
      return;
    }
    const run = {};
    activeRun.current = run;
    const ran = scenarios;
    setComparison({
      token,
      base: LOADING,
      scenarios: Object.fromEntries(ran.map((record) => [record.scenario.scenario_id, LOADING])),
    });
    // One request at a time: each column is its own complete analysis, and a
    // Lease-Level one is a full recomputation.
    const base = await analyzeBaseCell(dealId);
    if (activeRun.current === run) {
      setComparison((current) => (current === null ? current : { ...current, base }));
    }
    for (const record of ran) {
      const cell = await analyzeScenarioCell(record);
      if (activeRun.current !== run) {
        return;
      }
      setComparison((current) =>
        current === null
          ? current
          : { ...current, scenarios: { ...current.scenarios, [record.scenario.scenario_id]: cell } },
      );
    }
  }

  async function retryBase() {
    if (!isComparisonCurrent || dealId === null) {
      return;
    }
    const run = activeRun.current;
    setComparison((current) => (current === null ? current : { ...current, base: LOADING }));
    const base = await analyzeBaseCell(dealId);
    if (activeRun.current === run) {
      setComparison((current) => (current === null ? current : { ...current, base }));
    }
  }

  async function retryScenario(scenarioId: string) {
    const record = scenarios.find((candidate) => candidate.scenario.scenario_id === scenarioId);
    if (!isComparisonCurrent || record === undefined) {
      return;
    }
    const run = activeRun.current;
    const settle = (cell: ComparisonCell) =>
      setComparison((current) =>
        current === null ? current : { ...current, scenarios: { ...current.scenarios, [scenarioId]: cell } },
      );
    settle(LOADING);
    const cell = await analyzeScenarioCell(record);
    if (activeRun.current === run) {
      settle(cell);
    }
  }

  return {
    dealId,
    isDirty,
    listStatus: dealId === null ? 'unsaved' : list.status,
    loadError: list.status === 'error' ? list.message : null,
    retryLoad: () => {
      if (dealId === null) {
        return;
      }
      setList({ status: 'idle' });
      loadList(dealId, setList);
    },
    scenarios,
    targets,
    catalogStatus: catalog.status,
    catalogError: catalog.status === 'error' ? catalog.message : null,
    retryCatalog: () => {
      setCatalog({ status: 'idle' });
      loadCatalog(operatingMode, setCatalog);
    },
    canEdit,

    editor,
    feedback,
    isSaving,
    openNew: () => {
      if (!canEdit) {
        return;
      }
      setPendingDeleteId(null);
      setFeedback(null);
      setEditor({ scenarioId: null, name: '', description: '', rows: [blankRow()] });
    },
    openEdit: (scenarioId) => {
      const record = scenarios.find((candidate) => candidate.scenario.scenario_id === scenarioId);
      if (record === undefined || !canEdit) {
        return;
      }
      setPendingDeleteId(null);
      setFeedback(null);
      setEditor({
        scenarioId,
        name: record.scenario.name,
        description: record.scenario.description ?? '',
        rows: record.scenario.overrides.map((override) => ({
          key: nextRowKey(),
          target: override.target,
          operation: override.operation,
          value: scenarioValueToText(override.target, override.operation, override.value),
        })),
      });
    },
    cancelEdit: () => {
      setEditor(null);
      setFeedback(null);
    },
    setEditorName: (name) => setEditor((current) => (current === null ? current : { ...current, name })),
    setEditorDescription: (description) =>
      setEditor((current) => (current === null ? current : { ...current, description })),
    addRow: () =>
      setEditor((current) =>
        current === null ? current : { ...current, rows: [...current.rows, blankRow()] },
      ),
    removeRow: (key) =>
      setEditor((current) =>
        current === null ? current : { ...current, rows: current.rows.filter((row) => row.key !== key) },
      ),
    setRowTarget: (key, target) =>
      updateRow(key, (row) => {
        if (row.target === target) {
          return row;
        }
        // A new target can change the operations on offer and the units a value
        // is typed in, so the typed value is cleared rather than reinterpreted.
        const allowed = allowedOperations(target);
        const operation =
          allowed.length === 1
            ? allowed[0]
            : row.operation !== '' && allowed.includes(row.operation)
              ? row.operation
              : '';
        return { ...row, target, operation, value: '' };
      }),
    setRowOperation: (key, operation) =>
      updateRow(key, (row) => {
        const keepsValue =
          row.target !== '' &&
          row.operation !== '' &&
          operation !== '' &&
          sharesValueScale(row.target, row.operation, operation);
        return { ...row, operation, value: keepsValue ? row.value : '' };
      }),
    setRowValue: (key, value) => updateRow(key, (row) => ({ ...row, value })),
    saveEditor,

    pendingDeleteId,
    isDeleting,
    deleteError,
    requestDelete: (scenarioId) => {
      if (!canEdit) {
        return;
      }
      setDeleteError(null);
      setPendingDeleteId(scenarioId);
    },
    cancelDelete: () => {
      setPendingDeleteId(null);
      setDeleteError(null);
    },
    confirmDelete,

    comparison,
    isComparisonCurrent,
    isRunning,
    canRun,
    runComparison,
    retryBase,
    retryScenario,
  };
}
