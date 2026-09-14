/**
 * Phase 7 Gate P7.5 -- the Strategy state of one open Deal.
 *
 * A dedicated hook, never `App.tsx` state (the `useScenarios` precedent). It
 * owns the Deal's saved Strategies, the operating-outcome target catalog, the
 * Strategy editor and its feedback, and deletion.
 *
 * **One Deal per mount.** `RiskDecisionWorkspace` is keyed by mode and Deal id,
 * so nothing from one Deal can reach another.
 *
 * **Opt-in, read-only until the analyst acts.** Nothing is requested until Risk
 * is on screen; a read creates nothing; the first saved Strategy of a standalone
 * Deal materializes its hidden Investment through the Deal-scoped route. An
 * unsaved Deal has no Strategies, no temporary ids and no local stand-in.
 *
 * **The saved Deal is the base.** Strategies resolve against the Deal's saved
 * inputs. The saved Deal is read only when an editor opens -- its Base values
 * prefill a domain the first time the analyst enables it -- and read again after
 * a new save. While the base has unsaved edits, every Strategy change waits and
 * an open draft is kept exactly as typed, locked, until the base is clean.
 *
 * **Every rule is the backend's.** The editor checks presence and parsing
 * (`strategyForm.ts`); what a Strategy may say is decided by the P7.4 validator,
 * whose refusals are shown in its own words on the domain, row or Business Plan
 * item they name.
 */

import { useEffect, useRef, useState } from 'react';
import {
  createDealStrategy,
  deleteInvestmentStrategy,
  fetchStrategyTargetCatalog,
  getDeal,
  listDealStrategies,
  StrategyApiError,
  updateInvestmentStrategy,
} from './api';
import { businessPlanDraftFromInput, placeBusinessPlanApiIssues } from './businessPlan';
import type { BusinessPlanDraft, BusinessPlanInput } from './businessPlan';
import {
  blankStrategyDraft,
  buildStrategyRequest,
  domainNeedsBase,
  draftFromStrategy,
  strategyBaseValues,
} from './strategyForm';
import type {
  AcquisitionField,
  BusinessPlanChoice,
  FinancingField,
  OutcomeRowDraft,
  StrategyBaseValues,
  StrategyEditorDraft,
  StrategyEditorFeedback,
} from './strategyForm';
import type { InvestmentStrategy, StrategyDomain, StrategyTargetEntry } from './strategyTypes';
import type { OperatingMode } from './types';

export interface UseStrategiesOptions {
  operatingMode: OperatingMode;
  /** The open Deal's saved id, or `null` for a Deal that has never been saved. */
  dealId: string | null;
  /** Whether the base underwriting has unsaved edits. */
  isDirty: boolean;
  /** The Deal's `updated_at` as of its last Save or Open. */
  savedAt: string | null;
  /** Whether the Risk workspace is on screen. Nothing is requested before it is. */
  isActive: boolean;
}

type ListState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; strategies: InvestmentStrategy[] }
  | { status: 'error'; message: string };

type CatalogState =
  | { status: 'idle' }
  | { status: 'ready'; targets: StrategyTargetEntry[] }
  | { status: 'error'; message: string };

/** The saved Deal read for prefill, and the save it was read for. */
type BaseState =
  | { savedAt: string | null; status: 'ready'; values: StrategyBaseValues | null }
  | { savedAt: string | null; status: 'error' };

/** Whether the saved Base values a domain's first enable copies in are here:
 * being read, read, or unavailable because the read failed. */
export type StrategyBaseStatus = 'loading' | 'ready' | 'unavailable';

export type StrategyListStatus = 'unsaved' | 'idle' | 'loading' | 'ready' | 'error';

export interface StrategiesState {
  dealId: string | null;
  isDirty: boolean;
  listStatus: StrategyListStatus;
  loadError: string | null;
  retryLoad: () => void;
  strategies: InvestmentStrategy[];
  /** The operating-outcome targets for this Deal's mode. */
  targets: StrategyTargetEntry[];
  catalogStatus: 'idle' | 'ready' | 'error';
  catalogError: string | null;
  retryCatalog: () => void;
  /** Saved, clean and loaded: the only state a Strategy may be changed in. */
  canEdit: boolean;
  /** The saved Deal's Base values, once read for the current save. */
  base: StrategyBaseValues | null;
  /** An inherited domain cannot become strategy-specific -- and Inherit Base
   * cannot become a Custom Business Plan -- until this is `ready`. */
  baseStatus: StrategyBaseStatus;
  retryBase: () => void;

  editor: StrategyEditorDraft | null;
  feedback: StrategyEditorFeedback | null;
  isSaving: boolean;
  openNew: () => void;
  openEdit: (strategyId: string) => void;
  cancelEdit: () => void;
  setName: (name: string) => void;
  setDescription: (description: string) => void;
  setAcquisitionEnabled: (enabled: boolean) => void;
  setAcquisitionField: (field: AcquisitionField, value: string) => void;
  setFinancingEnabled: (enabled: boolean) => void;
  setFinancingField: (field: FinancingField, value: string) => void;
  setBusinessPlanChoice: (choice: BusinessPlanChoice) => void;
  setBusinessPlan: (plan: BusinessPlanDraft) => void;
  setOutcomeEnabled: (enabled: boolean) => void;
  addOutcomeRow: () => void;
  removeOutcomeRow: (key: string) => void;
  setOutcomeTarget: (key: string, target: string) => void;
  setOutcomeValue: (key: string, value: string) => void;
  setDispositionEnabled: (enabled: boolean) => void;
  setHoldPeriod: (value: string) => void;
  saveEditor: () => Promise<void>;

  pendingDeleteId: string | null;
  isDeleting: boolean;
  deleteError: string | null;
  requestDelete: (strategyId: string) => void;
  cancelDelete: () => void;
  confirmDelete: () => Promise<void>;
}

const NO_STRATEGIES: InvestmentStrategy[] = [];
const NO_TARGETS: StrategyTargetEntry[] = [];

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'The request could not be completed.';
}

function emptyFeedback(message: string): StrategyEditorFeedback {
  return { message, general: [], byDomain: {}, byRow: {}, planIssues: [] };
}

/** A refused save, each P7.4 issue placed where it belongs: on the outcome
 * row whose target it names, on the domain it names, or with the editor.
 * Business Plan issues are placed on their rows against the plan the request
 * carried. */
function feedbackFor(
  error: unknown,
  editor: StrategyEditorDraft,
  submittedPlan: BusinessPlanInput | null,
): StrategyEditorFeedback {
  if (!(error instanceof StrategyApiError)) {
    return emptyFeedback(messageOf(error));
  }
  const general: string[] = [];
  const byDomain: Partial<Record<StrategyDomain, string[]>> = {};
  const byRow: Record<string, string[]> = {};
  for (const issue of error.strategyIssues) {
    const row =
      issue.target === null
        ? undefined
        : editor.operatingOutcome.rows.find((candidate) => candidate.target === issue.target);
    if (row !== undefined) {
      (byRow[row.key] ??= []).push(issue.message);
    } else if (issue.domain !== null) {
      (byDomain[issue.domain] ??= []).push(issue.message);
    } else {
      general.push(issue.message);
    }
  }
  const planIssues =
    submittedPlan === null ? [] : placeBusinessPlanApiIssues(error.planIssues, submittedPlan);
  if (planIssues.length > 0) {
    (byDomain.business_plan ??= []).push('The backend refused Business Plan rows; each is marked below.');
  }
  for (const issue of error.issues) {
    general.push(issue.message);
  }
  if (error.strategyIssues.length === 0 && planIssues.length === 0 && general.length === 0) {
    general.push(...error.reasons);
  }
  return {
    message:
      error.status === 422
        ? 'The strategy was not saved. The backend refused it for these reasons:'
        : 'The strategy was not saved.',
    general,
    byDomain,
    byRow,
    planIssues,
  };
}

/** Each read sets state only when it settles, never synchronously from an
 * effect. */
function loadList(dealId: string, setList: (state: ListState) => void): void {
  listDealStrategies(dealId).then(
    (response) => setList({ status: 'ready', strategies: response.strategies }),
    (error: unknown) => setList({ status: 'error', message: messageOf(error) }),
  );
}

function loadCatalog(operatingMode: OperatingMode, setCatalog: (state: CatalogState) => void): void {
  fetchStrategyTargetCatalog().then(
    (response) => setCatalog({ status: 'ready', targets: response[operatingMode] ?? NO_TARGETS }),
    (error: unknown) => setCatalog({ status: 'error', message: messageOf(error) }),
  );
}

export function useStrategies({
  operatingMode,
  dealId,
  isDirty,
  savedAt,
  isActive,
}: UseStrategiesOptions): StrategiesState {
  const [list, setList] = useState<ListState>({ status: 'idle' });
  const [catalog, setCatalog] = useState<CatalogState>({ status: 'idle' });
  const [base, setBase] = useState<BaseState | null>(null);
  /** A new object asks for the saved Deal again after a failed read. */
  const [baseRetry, setBaseRetry] = useState<object>({});
  const [editor, setEditor] = useState<StrategyEditorDraft | null>(null);
  const [feedback, setFeedback] = useState<StrategyEditorFeedback | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  /** Outcome row keys: a per-mount sequence for React only, never an id. */
  const rowSequence = useRef(0);
  const listRequested = useRef(false);
  const catalogRequested = useRef(false);
  /** The save the latest Base read was requested for. */
  const baseRequestedFor = useRef<string | null | undefined>(undefined);

  function nextRowKey(): string {
    rowSequence.current += 1;
    return `outcome-row-${rowSequence.current}`;
  }

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

  const strategies = list.status === 'ready' ? list.strategies : NO_STRATEGIES;
  const targets = catalog.status === 'ready' ? catalog.targets : NO_TARGETS;
  const canEdit = dealId !== null && !isDirty && list.status === 'ready';
  const currentBase = base !== null && base.savedAt === savedAt ? base : null;
  const baseValues = currentBase?.status === 'ready' ? currentBase.values : null;
  const baseStatus: StrategyBaseStatus =
    currentBase === null ? 'loading' : baseValues !== null ? 'ready' : 'unavailable';
  const isEditorOpen = editor !== null;

  /** The saved Deal is read once per save while an editor is open: its Base
   * values prefill a domain the first time it is made strategy-specific. State
   * is set only when the read settles, and only for the save it was requested
   * for, so a slower read of an older save can never land. */
  useEffect(() => {
    if (!isEditorOpen || dealId === null || baseRequestedFor.current === savedAt) {
      return;
    }
    const requestedFor = savedAt;
    baseRequestedFor.current = requestedFor;
    getDeal(dealId).then(
      (deal) => {
        if (baseRequestedFor.current === requestedFor) {
          setBase({ savedAt: requestedFor, status: 'ready', values: strategyBaseValues(deal) });
        }
      },
      () => {
        if (baseRequestedFor.current === requestedFor) {
          setBase({ savedAt: requestedFor, status: 'error' });
        }
      },
    );
  }, [isEditorOpen, dealId, savedAt, baseRetry]);

  /** Every draft edit goes through here: while the base is dirty the draft is
   * kept exactly as typed but cannot change. */
  function editDraft(update: (draft: StrategyEditorDraft) => StrategyEditorDraft) {
    if (!canEdit) {
      return;
    }
    setEditor((current) => (current === null ? current : update(current)));
  }

  function updateRow(key: string, update: (row: OutcomeRowDraft) => OutcomeRowDraft) {
    editDraft((draft) => ({
      ...draft,
      operatingOutcome: {
        ...draft.operatingOutcome,
        rows: draft.operatingOutcome.rows.map((row) => (row.key === key ? update(row) : row)),
      },
    }));
  }

  function blankRow(): OutcomeRowDraft {
    return { key: nextRowKey(), target: '', value: '' };
  }

  async function saveEditor() {
    if (editor === null || dealId === null || !canEdit || isSaving) {
      return;
    }
    const built = buildStrategyRequest(editor, dealId);
    if ('feedback' in built) {
      setFeedback(built.feedback);
      return;
    }
    const existing =
      editor.strategyId === null
        ? null
        : strategies.find((record) => record.strategy.strategy_id === editor.strategyId);
    if (existing === undefined) {
      setFeedback(emptyFeedback('This strategy no longer exists. Cancel and reload the strategies.'));
      return;
    }
    setIsSaving(true);
    setFeedback(null);
    try {
      const saved =
        existing === null
          ? await createDealStrategy(dealId, built.draft)
          : await updateInvestmentStrategy(existing.investment_id, existing.strategy.strategy_id, built.draft);
      setList((current) =>
        current.status !== 'ready'
          ? current
          : {
              status: 'ready',
              strategies:
                existing === null
                  ? [...current.strategies, saved]
                  : current.strategies.map((record) =>
                      record.strategy.strategy_id === saved.strategy.strategy_id ? saved : record,
                    ),
            },
      );
      setEditor(null);
    } catch (error) {
      // The editor keeps every value the analyst typed.
      setFeedback(feedbackFor(error, editor, built.submittedPlan));
    } finally {
      setIsSaving(false);
    }
  }

  async function confirmDelete() {
    const record = strategies.find((candidate) => candidate.strategy.strategy_id === pendingDeleteId);
    if (record === undefined || !canEdit || isDeleting) {
      return;
    }
    setIsDeleting(true);
    setDeleteError(null);
    try {
      await deleteInvestmentStrategy(record.investment_id, record.strategy.strategy_id);
      setList((current) =>
        current.status !== 'ready'
          ? current
          : { status: 'ready', strategies: current.strategies.filter((candidate) => candidate !== record) },
      );
      if (editor?.strategyId === record.strategy.strategy_id) {
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
    strategies,
    targets,
    catalogStatus: catalog.status,
    catalogError: catalog.status === 'error' ? catalog.message : null,
    retryCatalog: () => {
      setCatalog({ status: 'idle' });
      loadCatalog(operatingMode, setCatalog);
    },
    canEdit,
    base: baseValues,
    baseStatus,
    retryBase: () => {
      baseRequestedFor.current = undefined;
      setBase(null);
      setBaseRetry({});
    },

    editor,
    feedback,
    isSaving,
    openNew: () => {
      if (!canEdit) {
        return;
      }
      setPendingDeleteId(null);
      setFeedback(null);
      setEditor(blankStrategyDraft());
    },
    openEdit: (strategyId) => {
      const record = strategies.find((candidate) => candidate.strategy.strategy_id === strategyId);
      if (record === undefined || !canEdit) {
        return;
      }
      setPendingDeleteId(null);
      setFeedback(null);
      setEditor(draftFromStrategy(record, nextRowKey));
    },
    cancelEdit: () => {
      setEditor(null);
      setFeedback(null);
    },
    setName: (name) => editDraft((draft) => ({ ...draft, name })),
    setDescription: (description) => editDraft((draft) => ({ ...draft, description })),
    // A first enable copies the whole domain from the saved Base -- or waits,
    // unchanged, until the Base values are here. A domain that already holds
    // explicit values keeps them and needs no Base. Nothing typed is replaced.
    setAcquisitionEnabled: (enabled) =>
      editDraft((draft) => {
        if (!enabled || !domainNeedsBase(draft, 'acquisition')) {
          return { ...draft, acquisition: { ...draft.acquisition, enabled } };
        }
        return baseValues === null ? draft : { ...draft, acquisition: { ...baseValues.acquisition, enabled } };
      }),
    setAcquisitionField: (field, value) =>
      editDraft((draft) => ({ ...draft, acquisition: { ...draft.acquisition, [field]: value } })),
    setFinancingEnabled: (enabled) =>
      editDraft((draft) => {
        if (!enabled || !domainNeedsBase(draft, 'financing')) {
          return { ...draft, financing: { ...draft.financing, enabled } };
        }
        return baseValues === null ? draft : { ...draft, financing: { ...baseValues.financing, enabled } };
      }),
    setFinancingField: (field, value) =>
      editDraft((draft) => ({ ...draft, financing: { ...draft.financing, [field]: value } })),
    setBusinessPlanChoice: (choice) =>
      editDraft((draft) => {
        // Inherit Base -> Custom starts from a copy of the current Base plan,
        // for convenience, so it waits until that plan is here. Once saved it
        // is the Strategy's own, independent plan. No Business Plan is an
        // explicit empty plan and needs no Base.
        if (choice === 'custom' && domainNeedsBase(draft, 'business_plan')) {
          return baseValues === null
            ? draft
            : { ...draft, businessPlan: { choice, plan: businessPlanDraftFromInput(baseValues.businessPlan) } };
        }
        return { ...draft, businessPlan: { choice, plan: draft.businessPlan.plan } };
      }),
    setBusinessPlan: (plan) => {
      editDraft((draft) => ({ ...draft, businessPlan: { ...draft.businessPlan, plan } }));
      // A refusal describes the plan that was sent; after an edit it may no
      // longer be true, so its row markings are cleared.
      setFeedback((current) => (current === null ? current : { ...current, planIssues: [] }));
    },
    setOutcomeEnabled: (enabled) =>
      editDraft((draft) => ({
        ...draft,
        operatingOutcome: {
          enabled,
          rows: enabled && draft.operatingOutcome.rows.length === 0 ? [blankRow()] : draft.operatingOutcome.rows,
        },
      })),
    addOutcomeRow: () =>
      editDraft((draft) => ({
        ...draft,
        operatingOutcome: { ...draft.operatingOutcome, rows: [...draft.operatingOutcome.rows, blankRow()] },
      })),
    removeOutcomeRow: (key) =>
      editDraft((draft) => ({
        ...draft,
        operatingOutcome: {
          ...draft.operatingOutcome,
          rows: draft.operatingOutcome.rows.filter((row) => row.key !== key),
        },
      })),
    // A new target can change the units a value is typed in, so the typed
    // value is cleared rather than reinterpreted.
    setOutcomeTarget: (key, target) =>
      updateRow(key, (row) => (row.target === target ? row : { ...row, target, value: '' })),
    setOutcomeValue: (key, value) => updateRow(key, (row) => ({ ...row, value })),
    setDispositionEnabled: (enabled) =>
      editDraft((draft) => {
        if (!enabled || !domainNeedsBase(draft, 'disposition')) {
          return { ...draft, disposition: { ...draft.disposition, enabled } };
        }
        return baseValues === null ? draft : { ...draft, disposition: { enabled, holdPeriod: baseValues.holdPeriod } };
      }),
    setHoldPeriod: (value) =>
      editDraft((draft) => ({ ...draft, disposition: { ...draft.disposition, holdPeriod: value } })),
    saveEditor,

    pendingDeleteId,
    isDeleting,
    deleteError,
    requestDelete: (strategyId) => {
      if (!canEdit) {
        return;
      }
      setDeleteError(null);
      setPendingDeleteId(strategyId);
    },
    cancelDelete: () => {
      setPendingDeleteId(null);
      setDeleteError(null);
    },
    confirmDelete,
  };
}
