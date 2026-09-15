/**
 * Phase 7 Gate P7.3 -- the Scenario state of one open Deal, and (P7.6) of one
 * visible Investment.
 *
 * P7 state lives in a dedicated hook, never in `App.tsx`, following
 * `useLeaseLevelDeal` and `useBusinessPlan`. The hook owns:
 * - the saved Scenarios;
 * - the target catalog (each Unit's operating mode decides its targets);
 * - the Scenario editor and its feedback;
 * - deletion.
 *
 * P7.5 moved comparison out: the Decision Matrix (`useDecisionMatrix`) is the
 * one comparison surface, so this hook manages Scenarios and nothing else.
 *
 * **One scope per mount.** The owner remounts the hook when the open Deal or
 * visible Investment changes, so nothing from one can reach another.
 *
 * **Two scopes, one implementation.** A Deal's Scenario overrides address the
 * Deal itself: the open Deal supplies the unit, and the Deal-scoped routes are
 * used -- the first saved Scenario materializes the Deal's hidden Investment. A
 * visible Investment's overrides each address one of its Units, chosen per row,
 * and the Investment-scoped routes are used: the Deal-scoped ones refuse a Unit
 * of a visible Investment. Each row's assumptions are its own Unit's mode's.
 *
 * **Opt-in, and read-only until the analyst acts.** Nothing is requested until
 * the Risk workspace is on screen, and a read never creates anything. A Deal
 * that has never been saved has no Scenarios: it gets no request, no temporary
 * id and no local stand-in.
 *
 * **The saved state is the base.** Persisted Scenarios resolve against the
 * saved inputs. While the base has unsaved changes, Scenario edits wait, and
 * an open draft is kept exactly as typed.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  createDealScenario,
  createInvestmentScenario,
  deleteInvestmentScenario,
  fetchScenarioTargetCatalog,
  listDealScenarios,
  listInvestmentScenarios,
  ScenarioApiError,
  updateInvestmentScenario,
} from './api';
import { FormValidationError } from './convert';
import { unitNames, withUnitNames } from './investmentCatalog';
import type { DecisionUnit, InvestmentDecisionScope } from './investmentCatalog';
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
  ScenarioTargetCatalog,
  ScenarioTargetEntry,
} from './scenarioTypes';
import type { OperatingMode } from './types';

export interface UseScenariosOptions {
  /** The open Deal's operating mode; `null` for a visible Investment, whose
   * Units each have their own. */
  operatingMode: OperatingMode | null;
  /** The open Deal's saved id, or `null` for a Deal that has never been saved. */
  dealId: string | null;
  /** Whether the base (the Deal, or the Investment) has unsaved edits. */
  isDirty: boolean;
  /** Whether the Risk workspace is on screen. Nothing is requested before it is. */
  isActive: boolean;
  /** P7.6: a visible Investment's scope. When present, every read and write
   * uses the Investment-scoped routes and each row names its Unit. */
  investment?: InvestmentDecisionScope | null;
}

/** One override row in the editor, as typed. `key` identifies the row for
 * React only and never reaches the backend. `unitId` is the Unit the row
 * addresses in a visible Investment; a Deal's rows leave it blank, because the
 * open Deal is the unit. */
export interface ScenarioEditorRow {
  key: string;
  unitId: string;
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
  | { status: 'ready'; catalog: ScenarioTargetCatalog }
  | { status: 'error'; message: string };

export type ScenarioListStatus = 'unsaved' | 'idle' | 'loading' | 'ready' | 'error';

export interface ScenariosState {
  dealId: string | null;
  /** P7.6: the visible Investment these Scenarios belong to, or `null`. */
  investment: InvestmentDecisionScope | null;
  /** The Units a row may address: none for a Deal (the Deal is implicit),
   * every Unit of a visible Investment. */
  units: readonly DecisionUnit[];
  isDirty: boolean;
  listStatus: ScenarioListStatus;
  loadError: string | null;
  retryLoad: () => void;
  scenarios: InvestmentScenario[];
  /** The registry's targets for the open Deal's operating mode. */
  targets: ScenarioTargetEntry[];
  /** The registry's targets for one row: its Unit's mode in a visible
   * Investment, the Deal's mode otherwise. */
  targetsFor: (unitId: string) => ScenarioTargetEntry[];
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
  setRowUnit: (key: string, unitId: string) => void;
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
const NO_UNITS: readonly DecisionUnit[] = [];

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'The request could not be completed.';
}

/** The editor's rows as a Scenario body, or the presence and parsing problems
 * that stop it being sent. `unitId` is the open Deal; `null` means each row
 * names its own Unit. Presence and parsing only: every rule about what a
 * Scenario may say is the backend's. */
function buildDraft(
  editor: ScenarioEditorDraft,
  unitId: string | null,
): { draft: ScenarioDraft } | { feedback: ScenarioEditorFeedback } {
  const general: string[] = [];
  const byRow: Record<string, string[]> = {};
  if (editor.name.trim() === '') {
    general.push('Enter a scenario name.');
  }
  const overrides: ScenarioOverride[] = [];
  for (const row of editor.rows) {
    const rowUnit = unitId ?? row.unitId;
    if (rowUnit === '') {
      byRow[row.key] = ['Choose a unit.'];
      continue;
    }
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
        unit_id: rowUnit,
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

/** A refused save, with each P7.1 issue placed on the row whose Unit and
 * target it names. Issues no row owns are listed with the editor. A visible
 * Investment's messages name each Unit rather than quote its id. */
function feedbackFor(
  error: unknown,
  editor: ScenarioEditorDraft,
  byUnit: boolean,
  names: Readonly<Record<string, string>>,
): ScenarioEditorFeedback {
  if (!(error instanceof ScenarioApiError)) {
    return { message: messageOf(error), general: [], byRow: {} };
  }
  const named = (message: string) => withUnitNames(message, names);
  const general: string[] = [];
  const byRow: Record<string, string[]> = {};
  for (const issue of error.scenarioIssues) {
    const row =
      issue.target === null
        ? undefined
        : editor.rows.find(
            (candidate) =>
              candidate.target === issue.target && (!byUnit || issue.unit_id === null || candidate.unitId === issue.unit_id),
          );
    if (row === undefined) {
      general.push(named(issue.message));
    } else {
      (byRow[row.key] ??= []).push(named(issue.message));
    }
  }
  for (const issue of [...error.leaseIssues, ...error.issues]) {
    general.push(named(issue.message));
  }
  if (error.scenarioIssues.length === 0 && general.length === 0) {
    general.push(...error.reasons.map(named));
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

/** Reads the Scenarios. State is set only when the request settles, never
 * synchronously from an effect. A visible Investment's come from its own
 * route. */
function loadList(
  dealId: string | null,
  investmentId: string | null,
  setList: (state: ListState) => void,
): void {
  const request =
    investmentId !== null
      ? listInvestmentScenarios(investmentId)
      : dealId !== null
        ? listDealScenarios(dealId).then((response) => response.scenarios)
        : null;
  request?.then(
    (scenarios) => setList({ status: 'ready', scenarios }),
    (error: unknown) => setList({ status: 'error', message: messageOf(error) }),
  );
}

/** Reads the registry's catalog, every mode's targets. */
function loadCatalog(setCatalog: (state: CatalogState) => void): void {
  fetchScenarioTargetCatalog().then(
    (catalog) => setCatalog({ status: 'ready', catalog }),
    (error: unknown) => setCatalog({ status: 'error', message: messageOf(error) }),
  );
}

export function useScenarios({
  operatingMode,
  dealId,
  isDirty,
  isActive,
  investment = null,
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

  const investmentId = investment?.investmentId ?? null;
  const scopeId = investmentId ?? dealId;
  const units = investment === null ? NO_UNITS : investment.units;
  const names = useMemo(() => (investment === null ? {} : unitNames(investment.units)), [investment]);

  function nextRowKey(): string {
    rowSequence.current += 1;
    return `override-row-${rowSequence.current}`;
  }

  /** A new row. A visible Investment with one Unit names it; with several,
   * the analyst chooses. */
  function blankRow(): ScenarioEditorRow {
    const unitId = units.length === 1 ? units[0].unitId : '';
    return { key: nextRowKey(), unitId, target: '', operation: '', value: '' };
  }

  /** Each read is requested once per mount; a retry asks again explicitly. */
  const listRequested = useRef(false);
  const catalogRequested = useRef(false);

  useEffect(() => {
    if (!isActive || scopeId === null || listRequested.current) {
      return;
    }
    listRequested.current = true;
    loadList(dealId, investmentId, setList);
  }, [isActive, scopeId, dealId, investmentId]);

  useEffect(() => {
    if (!isActive || scopeId === null || catalogRequested.current) {
      return;
    }
    catalogRequested.current = true;
    loadCatalog(setCatalog);
  }, [isActive, scopeId]);

  const scenarios = list.status === 'ready' ? list.scenarios : NO_SCENARIOS;
  const targets =
    catalog.status === 'ready' && operatingMode !== null ? (catalog.catalog[operatingMode] ?? NO_TARGETS) : NO_TARGETS;
  const canEdit = scopeId !== null && !isDirty && list.status === 'ready';

  function targetsFor(unitId: string): ScenarioTargetEntry[] {
    if (investment === null) {
      return targets;
    }
    const unit = units.find((candidate) => candidate.unitId === unitId);
    return catalog.status === 'ready' && unit !== undefined
      ? (catalog.catalog[unit.operatingMode] ?? NO_TARGETS)
      : NO_TARGETS;
  }

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

  function allowedOperations(unitId: string, target: string): ScenarioOperation[] {
    return targetsFor(unitId).find((entry) => entry.target === target)?.allowed_operations ?? [];
  }

  async function saveEditor() {
    if (editor === null || scopeId === null || !canEdit || isSaving) {
      return;
    }
    const built = buildDraft(editor, investment === null ? scopeId : null);
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
      let saved: InvestmentScenario;
      if (existing !== null) {
        saved = await updateInvestmentScenario(existing.investment_id, existing.scenario.scenario_id, built.draft);
      } else if (investmentId !== null) {
        saved = await createInvestmentScenario(investmentId, built.draft);
      } else {
        saved = await createDealScenario(scopeId, built.draft);
      }
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
      setFeedback(feedbackFor(error, editor, investment !== null, names));
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
      // When no Scenario and no Strategy remains, the backend also removed a
      // Deal's hidden Investment (P7.4): the Deal is a plain Deal again. A
      // visible Investment is never removed by this.
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
      setDeleteError(withUnitNames(messageOf(error), names));
    } finally {
      setIsDeleting(false);
    }
  }

  return {
    dealId,
    investment,
    units,
    isDirty,
    listStatus: scopeId === null ? 'unsaved' : list.status,
    loadError: list.status === 'error' ? list.message : null,
    retryLoad: () => {
      if (scopeId === null) {
        return;
      }
      setList({ status: 'idle' });
      loadList(dealId, investmentId, setList);
    },
    scenarios,
    targets,
    targetsFor,
    catalogStatus: catalog.status,
    catalogError: catalog.status === 'error' ? catalog.message : null,
    retryCatalog: () => {
      setCatalog({ status: 'idle' });
      loadCatalog(setCatalog);
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
          unitId: investment === null ? '' : override.unit_id,
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
    // A new Unit offers its own mode's assumptions, so everything chosen
    // under the previous Unit is cleared rather than carried across.
    setRowUnit: (key, unitId) =>
      updateRow(key, (row) =>
        row.unitId === unitId ? row : { ...row, unitId, target: '', operation: '', value: '' },
      ),
    setRowTarget: (key, target) =>
      updateRow(key, (row) => {
        if (row.target === target) {
          return row;
        }
        // A new target can change the operations on offer and the units a value
        // is typed in, so the typed value is cleared rather than reinterpreted.
        const allowed = allowedOperations(row.unitId, target);
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
