/**
 * Phase 7 Gate P7.3 -- the Scenario state of one open Deal.
 *
 * P7 state lives in a dedicated hook, never in `App.tsx`, following
 * `useLeaseLevelDeal` and `useBusinessPlan`. The hook owns:
 * - the Deal's saved Scenarios;
 * - the target catalog for the Deal's operating mode;
 * - the Scenario editor and its feedback;
 * - deletion.
 *
 * P7.5 moved comparison out: the Strategy x Scenario Decision Matrix
 * (`useDecisionMatrix`) is the one comparison surface, so this hook manages
 * Scenarios and nothing else.
 *
 * **One Deal per mount.** The owner remounts the hook when the open Deal changes
 * (`RiskDecisionWorkspace` is keyed by mode and Deal id), so nothing from one
 * Deal can reach another by construction.
 *
 * **Opt-in, and read-only until the analyst acts.** Nothing is requested until
 * the Risk workspace is on screen, and a read never creates anything. The first
 * Scenario (or Strategy) the analyst saves is what materializes the Deal's
 * hidden Investment, through the route that owns that. A Deal that has never
 * been saved has no Scenarios: it gets no request, no temporary id and no local
 * stand-in.
 *
 * **The saved Deal is the base.** Persisted Scenarios resolve against the
 * Deal's *saved* inputs. While the base underwriting has unsaved edits,
 * Scenario edits wait, and an open draft is kept exactly as typed.
 */

import { useEffect, useRef, useState } from 'react';
import {
  createDealScenario,
  deleteInvestmentScenario,
  fetchScenarioTargetCatalog,
  listDealScenarios,
  ScenarioApiError,
  updateInvestmentScenario,
} from './api';
import { FormValidationError } from './convert';
import {
  scenarioTargetLabel,
  scenarioValueToText,
  scenarioValueToWire,
  sharesValueScale,
} from './scenarioCatalog';
import type {
  InvestmentScenario,
  ScenarioDraft,
  ScenarioOperation,
  ScenarioOverride,
  ScenarioTargetEntry,
} from './scenarioTypes';
import type { OperatingMode } from './types';

export interface UseScenariosOptions {
  operatingMode: OperatingMode;
  /** The open Deal's saved id, or `null` for a Deal that has never been saved. */
  dealId: string | null;
  /** Whether the base underwriting has unsaved edits. */
  isDirty: boolean;
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
  | { status: 'ready'; scenarios: InvestmentScenario[] }
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
}

/** Why Scenario controls are locked while the deal is dirty. */
export const SAVE_BEFORE_SCENARIOS_MESSAGE =
  'Save base underwriting changes before editing or running scenarios.';

const NO_SCENARIOS: InvestmentScenario[] = [];
const NO_TARGETS: ScenarioTargetEntry[] = [];

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'The request could not be completed.';
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
    (response) => setList({ status: 'ready', scenarios: response.scenarios }),
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

  /** Every draft edit goes through here. While the base has unsaved changes
   * the draft is kept exactly as typed, but it cannot change: Scenario edits
   * wait for the base to be saved. */
  function editDraft(update: (draft: ScenarioEditorDraft) => ScenarioEditorDraft) {
    if (!canEdit) {
      return;
    }
    setEditor((current) => (current === null ? current : update(current)));
  }

  function updateRow(key: string, update: (row: ScenarioEditorRow) => ScenarioEditorRow) {
    editDraft((draft) => ({
      ...draft,
      rows: draft.rows.map((row) => (row.key === key ? update(row) : row)),
    }));
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
      // When no Scenario and no Strategy remains, the backend also removed
      // the hidden Investment (P7.4): the Deal is a plain Deal again.
      setList((current) =>
        current.status !== 'ready'
          ? current
          : {
              status: 'ready',
              scenarios: current.scenarios.filter((candidate) => candidate !== record),
            },
      );
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
    setEditorName: (name) => editDraft((draft) => ({ ...draft, name })),
    setEditorDescription: (description) => editDraft((draft) => ({ ...draft, description })),
    addRow: () => editDraft((draft) => ({ ...draft, rows: [...draft.rows, blankRow()] })),
    removeRow: (key) =>
      editDraft((draft) => ({ ...draft, rows: draft.rows.filter((row) => row.key !== key) })),
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
  };
}
