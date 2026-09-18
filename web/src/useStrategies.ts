/**
 * Phase 7 Gate P7.5 -- the Strategy state of one open Deal, and (P7.6) of one
 * visible Investment.
 *
 * A dedicated hook, never `App.tsx` state (the `useScenarios` precedent). It
 * owns the saved Strategies, the operating-outcome target catalog, the
 * Strategy editor and its feedback, and deletion.
 *
 * **One scope per mount.** `RiskDecisionWorkspace` is keyed by mode and Deal
 * id, or by the visible Investment, so nothing from one can reach another.
 *
 * **Two scopes, one implementation.** A Deal's Strategies address the Deal
 * alone and use the Deal-scoped routes: the first saved Strategy of a
 * standalone Deal materializes its hidden Investment. A visible Investment's
 * Strategies address its Units and use the Investment-scoped routes -- the
 * Deal-scoped ones refuse a Unit of a visible Investment. Every Unit is in
 * every Strategy; each Unit's section offers the targets of that Unit's own
 * operating mode.
 *
 * **Opt-in, read-only until the analyst acts.** Nothing is requested until Risk
 * is on screen; a read creates nothing. An unsaved Deal has no Strategies, no
 * temporary ids and no local stand-in.
 *
 * **Each Unit's saved Deal is its base.** Strategies resolve against the saved
 * inputs. Each Unit's saved Deal is read when an editor opens -- its Base values
 * prefill a domain of *that* Unit the first time the analyst enables it -- and
 * read again after that Unit's next save. A Unit whose read failed offers Retry
 * and cannot prefill; every other Unit stays usable. While the base has unsaved
 * edits, every Strategy change waits and an open draft is kept exactly as
 * typed, locked, until the base is clean.
 *
 * **Every rule is the backend's.** The editor checks presence and parsing
 * (`strategyForm.ts`); what a Strategy may say is decided by the P7.4 / P7.6
 * validators, whose refusals are shown in their own words on the Unit, domain,
 * row or Business Plan item they name.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  createDealStrategy,
  deleteInvestmentStrategy,
  fetchStrategyTargetCatalog,
  getDeal,
  InvestmentStrategyApiError,
  listDealStrategies,
  listInvestmentStrategies,
  saveInvestmentStrategy,
  StrategyApiError,
  updateInvestmentStrategy,
} from './api';
import { businessPlanDraftFromInput, placeBusinessPlanApiIssues } from './businessPlan';
import type { BusinessPlanDraft } from './businessPlan';
import { formFromStructure } from './capitalStructureForm';
import type { CapitalStructureForm } from './capitalStructureForm';
import { formFromPartnership } from './partnershipForm';
import type { PartnershipForm } from './partnershipForm';
import type { Partnership } from './partnershipTypes';
import type { CapitalStructure } from './capitalTypes';
import { unitNames, withUnitNames } from './investmentCatalog';
import type { DecisionUnit, InvestmentDecisionScope } from './investmentCatalog';
import {
  blankStrategyDraft,
  buildStrategyRequest,
  domainNeedsBase,
  draftFromStrategy,
  strategyBaseValues,
  unitFeedbackOf,
} from './strategyForm';
import type {
  AcquisitionField,
  BuiltStrategyRequest,
  BusinessPlanChoice,
  FinancingField,
  OutcomeRowDraft,
  StrategyBaseValues,
  StrategyEditorDraft,
  StrategyEditorFeedback,
  StrategyUnitDraft,
} from './strategyForm';
import type { InvestmentStrategy, StrategyTargetCatalog, StrategyTargetEntry } from './strategyTypes';
import type { OperatingMode } from './types';

export interface UseStrategiesOptions {
  /** The open Deal's operating mode; `null` for a visible Investment, whose
   * Units each have their own. */
  operatingMode: OperatingMode | null;
  /** The open Deal's saved id, or `null` for a Deal that has never been saved. */
  dealId: string | null;
  /** Whether the base (the Deal, or the Investment) has unsaved edits. */
  isDirty: boolean;
  /** The Deal's `updated_at` as of its last Save or Open. */
  savedAt: string | null;
  /** Whether the Risk workspace is on screen. Nothing is requested before it is. */
  isActive: boolean;
  /** P7.6: a visible Investment's scope. When present, every read and write
   * uses the Investment-scoped routes and the Deal fields are not read. */
  investment?: InvestmentDecisionScope | null;
  /** P7.8B: the saved Base Capital Structure. Making that domain
   * strategy-specific for the first time starts from a copy of it, every
   * position keeping its id (P-8), exactly as a Custom Business Plan starts
   * from a copy of the Base plan. */
  baseCapitalStructure?: CapitalStructure;
  /** P7.9 Stage 3: the saved Base Partnership, or `null` when there is none.
   * Making that domain strategy-specific for the first time starts from a copy
   * of it, every partner and tier keeping its id (P-8), exactly as the Capital
   * Structure domain does. */
  basePartnership?: Partnership | null;
}

type ListState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; strategies: InvestmentStrategy[] }
  | { status: 'error'; message: string };

type CatalogState =
  | { status: 'idle' }
  | { status: 'ready'; catalog: StrategyTargetCatalog }
  | { status: 'error'; message: string };

/** One Unit's saved Deal read for prefill, and the save it was read for. */
type BaseState =
  | { savedAt: string | null; status: 'ready'; values: StrategyBaseValues | null }
  | { savedAt: string | null; status: 'error' };

/** Whether the saved Base values a domain's first enable copies in are here:
 * being read, read, or unavailable because the read failed. */
export type StrategyBaseStatus = 'loading' | 'ready' | 'unavailable';

export type StrategyListStatus = 'unsaved' | 'idle' | 'loading' | 'ready' | 'error';

export interface StrategiesState {
  dealId: string | null;
  /** P7.6: the visible Investment these Strategies belong to, or `null` for a
   * Deal's. */
  investment: InvestmentDecisionScope | null;
  /** The Units every Strategy addresses: the Deal alone, or each Unit of the
   * visible Investment, in presentation order. */
  units: readonly DecisionUnit[];
  isDirty: boolean;
  listStatus: StrategyListStatus;
  loadError: string | null;
  retryLoad: () => void;
  strategies: InvestmentStrategy[];
  /** The operating-outcome targets one Unit's own mode offers. */
  targetsFor: (unitId: string) => StrategyTargetEntry[];
  catalogStatus: 'idle' | 'ready' | 'error';
  catalogError: string | null;
  retryCatalog: () => void;
  /** Saved, clean and loaded: the only state a Strategy may be changed in. */
  canEdit: boolean;
  /** One Unit's saved Base values, once read for its current save. */
  baseFor: (unitId: string) => StrategyBaseValues | null;
  /** An inherited domain of this Unit cannot become strategy-specific -- and
   * Inherit Base cannot become a Custom Business Plan -- until this is `ready`. */
  baseStatusFor: (unitId: string) => StrategyBaseStatus;
  retryBase: (unitId: string) => void;

  editor: StrategyEditorDraft | null;
  feedback: StrategyEditorFeedback | null;
  isSaving: boolean;
  openNew: () => void;
  openEdit: (strategyId: string) => void;
  cancelEdit: () => void;
  setName: (name: string) => void;
  setDescription: (description: string) => void;
  /** The whole-transaction domain: inherit the Base structure, or state this
   * Strategy's own. Stated once, never per Unit. */
  setCapitalStructureChoice: (choice: 'inherit' | 'specific') => void;
  setCapitalStructure: (form: CapitalStructureForm) => void;
  setPartnershipChoice: (choice: 'inherit' | 'none' | 'specific') => void;
  setPartnership: (form: PartnershipForm) => void;
  setAcquisitionEnabled: (unitId: string, enabled: boolean) => void;
  setAcquisitionField: (unitId: string, field: AcquisitionField, value: string) => void;
  setFinancingEnabled: (unitId: string, enabled: boolean) => void;
  setFinancingField: (unitId: string, field: FinancingField, value: string) => void;
  setBusinessPlanChoice: (unitId: string, choice: BusinessPlanChoice) => void;
  setBusinessPlan: (unitId: string, plan: BusinessPlanDraft) => void;
  setOutcomeEnabled: (unitId: string, enabled: boolean) => void;
  addOutcomeRow: (unitId: string) => void;
  removeOutcomeRow: (unitId: string, key: string) => void;
  setOutcomeTarget: (unitId: string, key: string, target: string) => void;
  setOutcomeValue: (unitId: string, key: string, value: string) => void;
  setDispositionEnabled: (unitId: string, enabled: boolean) => void;
  setHoldPeriod: (unitId: string, value: string) => void;
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
const NO_UNITS: readonly DecisionUnit[] = [];
/** No Base structure to copy: the analyst states the whole stack. */
const NO_CAPITAL_STRUCTURE: CapitalStructure = { positions: [] };

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'The request could not be completed.';
}

function emptyFeedback(message: string): StrategyEditorFeedback {
  return { message, general: [], byUnit: {}, byRow: {} };
}

/** A refused save, each issue placed where it belongs: on the outcome row
 * whose Unit and target it names, on the Unit domain it names, or with the
 * editor. Business Plan issues are placed on their Unit's rows against the plan
 * the request carried for that Unit. A visible Investment's messages name each
 * Unit rather than quote its id. */
function feedbackFor(
  error: unknown,
  editor: StrategyEditorDraft,
  built: BuiltStrategyRequest,
  names: Readonly<Record<string, string>>,
): StrategyEditorFeedback {
  if (!(error instanceof StrategyApiError)) {
    return emptyFeedback(messageOf(error));
  }
  const feedback = emptyFeedback(
    error.status === 422
      ? 'The strategy was not saved. The backend refused it for these reasons:'
      : 'The strategy was not saved.',
  );
  const named = (message: string) => withUnitNames(message, names);
  const onlyUnit = editor.units.length === 1 ? editor.units[0] : undefined;
  const unitOf = (unitId: string | null): StrategyUnitDraft | undefined =>
    unitId === null ? onlyUnit : editor.units.find((unit) => unit.unitId === unitId);

  for (const issue of error.strategyIssues) {
    const unit = unitOf(issue.unit_id);
    const row =
      issue.target === null || unit === undefined
        ? undefined
        : unit.operatingOutcome.rows.find((candidate) => candidate.target === issue.target);
    if (row !== undefined) {
      (feedback.byRow[row.key] ??= []).push(named(issue.message));
    } else if (unit !== undefined && issue.domain !== null) {
      (unitFeedbackOf(feedback, unit.unitId).byDomain[issue.domain] ??= []).push(named(issue.message));
    } else {
      feedback.general.push(named(issue.message));
    }
  }

  let placedPlanIssues = false;
  if (error instanceof InvestmentStrategyApiError) {
    error.planIssues.forEach((issue, position) => {
      const overlay = built.draft.overlays[error.planIssueOverlays[position]];
      const plan = overlay === undefined ? undefined : built.submittedPlans[overlay.unit_id];
      if (overlay === undefined || plan === undefined) {
        feedback.general.push(named(issue.message));
        return;
      }
      unitFeedbackOf(feedback, overlay.unit_id).planIssues.push(...placeBusinessPlanApiIssues([issue], plan));
      placedPlanIssues = true;
    });
  } else if (onlyUnit !== undefined) {
    const plan = built.submittedPlans[onlyUnit.unitId];
    const placed = plan === undefined ? [] : placeBusinessPlanApiIssues(error.planIssues, plan);
    if (placed.length > 0) {
      unitFeedbackOf(feedback, onlyUnit.unitId).planIssues = placed;
      placedPlanIssues = true;
    }
  }
  for (const [unitId, share] of Object.entries(feedback.byUnit)) {
    if (share.planIssues.length > 0) {
      (unitFeedbackOf(feedback, unitId).byDomain.business_plan ??= []).push(
        'The backend refused Business Plan rows; each is marked below.',
      );
    }
  }
  for (const issue of error.issues) {
    feedback.general.push(issue.message);
  }
  if (error.strategyIssues.length === 0 && !placedPlanIssues && feedback.general.length === 0) {
    feedback.general.push(...error.reasons.map(named));
  }
  return feedback;
}

/** Each read sets state only when it settles, never synchronously from an
 * effect. A visible Investment's Strategies come from its own route. */
function loadList(
  dealId: string | null,
  investmentId: string | null,
  setList: (state: ListState) => void,
): void {
  const request =
    investmentId !== null
      ? listInvestmentStrategies(investmentId)
      : dealId !== null
        ? listDealStrategies(dealId).then((response) => response.strategies)
        : null;
  request?.then(
    (strategies) => setList({ status: 'ready', strategies }),
    (error: unknown) => setList({ status: 'error', message: messageOf(error) }),
  );
}

function loadCatalog(setCatalog: (state: CatalogState) => void): void {
  fetchStrategyTargetCatalog().then(
    (catalog) => setCatalog({ status: 'ready', catalog }),
    (error: unknown) => setCatalog({ status: 'error', message: messageOf(error) }),
  );
}

export function useStrategies({
  operatingMode,
  dealId,
  isDirty,
  savedAt,
  isActive,
  investment = null,
  baseCapitalStructure = NO_CAPITAL_STRUCTURE,
  basePartnership = null,
}: UseStrategiesOptions): StrategiesState {
  const [list, setList] = useState<ListState>({ status: 'idle' });
  const [catalog, setCatalog] = useState<CatalogState>({ status: 'idle' });
  const [bases, setBases] = useState<Record<string, BaseState>>({});
  /** A new object asks for the failed Base reads again. */
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
  /** Per Unit: the save its latest Base read was requested for. */
  const baseRequestedFor = useRef(new Map<string, string | null>());

  const investmentId = investment?.investmentId ?? null;
  const scopeId = investmentId ?? dealId;
  const units = useMemo<readonly DecisionUnit[]>(() => {
    if (investment !== null) {
      return investment.units;
    }
    if (dealId === null || operatingMode === null) {
      return NO_UNITS;
    }
    return [{ unitId: dealId, dealName: '', label: null, operatingMode, savedAt }];
  }, [investment, dealId, operatingMode, savedAt]);
  const names = useMemo(() => (investment === null ? {} : unitNames(investment.units)), [investment]);

  function nextRowKey(): string {
    rowSequence.current += 1;
    return `outcome-row-${rowSequence.current}`;
  }

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

  const strategies = list.status === 'ready' ? list.strategies : NO_STRATEGIES;
  const canEdit = scopeId !== null && !isDirty && list.status === 'ready';
  const isEditorOpen = editor !== null;

  function currentBase(unitId: string): BaseState | null {
    const unit = units.find((candidate) => candidate.unitId === unitId);
    const base = bases[unitId];
    return unit !== undefined && base !== undefined && base.savedAt === unit.savedAt ? base : null;
  }

  function baseFor(unitId: string): StrategyBaseValues | null {
    const base = currentBase(unitId);
    return base?.status === 'ready' ? base.values : null;
  }

  function baseStatusFor(unitId: string): StrategyBaseStatus {
    const base = currentBase(unitId);
    if (base === null) {
      return 'loading';
    }
    return base.status === 'ready' && base.values !== null ? 'ready' : 'unavailable';
  }

  /** Each Unit's saved Deal is read once per save while an editor is open: its
   * Base values prefill a domain of that Unit the first time it is made
   * strategy-specific. State is set only when a read settles, and only for the
   * save it was requested for, so a slower read of an older save never lands.
   * One Unit's failure leaves every other Unit's read alone. */
  useEffect(() => {
    if (!isEditorOpen) {
      return;
    }
    const requested = baseRequestedFor.current;
    for (const unit of units) {
      if (requested.has(unit.unitId) && requested.get(unit.unitId) === unit.savedAt) {
        continue;
      }
      const { unitId, savedAt: requestedFor } = unit;
      requested.set(unitId, requestedFor);
      getDeal(unitId).then(
        (deal) => {
          if (requested.get(unitId) === requestedFor) {
            setBases((current) => ({
              ...current,
              [unitId]: { savedAt: requestedFor, status: 'ready', values: strategyBaseValues(deal) },
            }));
          }
        },
        () => {
          if (requested.get(unitId) === requestedFor) {
            setBases((current) => ({ ...current, [unitId]: { savedAt: requestedFor, status: 'error' } }));
          }
        },
      );
    }
  }, [isEditorOpen, units, baseRetry]);

  /** Every draft edit goes through here: while the base is dirty the draft is
   * kept exactly as typed but cannot change. */
  function editDraft(update: (draft: StrategyEditorDraft) => StrategyEditorDraft) {
    if (!canEdit) {
      return;
    }
    setEditor((current) => (current === null ? current : update(current)));
  }

  function editUnit(unitId: string, update: (unit: StrategyUnitDraft) => StrategyUnitDraft) {
    editDraft((draft) => ({
      ...draft,
      units: draft.units.map((unit) => (unit.unitId === unitId ? update(unit) : unit)),
    }));
  }

  function updateRow(unitId: string, key: string, update: (row: OutcomeRowDraft) => OutcomeRowDraft) {
    editUnit(unitId, (unit) => ({
      ...unit,
      operatingOutcome: {
        ...unit.operatingOutcome,
        rows: unit.operatingOutcome.rows.map((row) => (row.key === key ? update(row) : row)),
      },
    }));
  }

  function blankRow(): OutcomeRowDraft {
    return { key: nextRowKey(), target: '', value: '' };
  }

  async function saveEditor() {
    if (editor === null || scopeId === null || !canEdit || isSaving) {
      return;
    }
    const built = buildStrategyRequest(editor);
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
      let saved: InvestmentStrategy;
      if (investmentId !== null) {
        saved = await saveInvestmentStrategy(
          investmentId,
          existing === null ? null : existing.strategy.strategy_id,
          built.draft,
        );
      } else if (existing === null) {
        saved = await createDealStrategy(scopeId, built.draft);
      } else {
        saved = await updateInvestmentStrategy(existing.investment_id, existing.strategy.strategy_id, built.draft);
      }
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
      setFeedback(feedbackFor(error, editor, built, names));
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
      setDeleteError(withUnitNames(messageOf(error), names));
    } finally {
      setIsDeleting(false);
    }
  }

  /** A first enable copies the Unit's whole domain from its saved Base -- or
   * waits, unchanged, until that Unit's Base values are here. A domain that
   * already holds explicit values keeps them and needs no Base. Nothing typed
   * is replaced, and no other Unit's Base is ever read. */
  function enableFromBase(
    unitId: string,
    domain: 'acquisition' | 'financing' | 'disposition',
    enabled: boolean,
  ) {
    const base = baseFor(unitId);
    editUnit(unitId, (unit) => {
      const copiesBase = enabled && domainNeedsBase(unit, domain);
      if (copiesBase && base === null) {
        return unit;
      }
      switch (domain) {
        case 'acquisition':
          return {
            ...unit,
            acquisition: copiesBase && base !== null ? { ...base.acquisition, enabled } : { ...unit.acquisition, enabled },
          };
        case 'financing':
          return {
            ...unit,
            financing: copiesBase && base !== null ? { ...base.financing, enabled } : { ...unit.financing, enabled },
          };
        case 'disposition':
          return {
            ...unit,
            disposition:
              copiesBase && base !== null
                ? { enabled, holdPeriod: base.holdPeriod }
                : { ...unit.disposition, enabled },
          };
      }
    });
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
    strategies,
    targetsFor: (unitId) => {
      const unit = units.find((candidate) => candidate.unitId === unitId);
      return catalog.status === 'ready' && unit !== undefined
        ? (catalog.catalog[unit.operatingMode] ?? NO_TARGETS)
        : NO_TARGETS;
    },
    catalogStatus: catalog.status,
    catalogError: catalog.status === 'error' ? catalog.message : null,
    retryCatalog: () => {
      setCatalog({ status: 'idle' });
      loadCatalog(setCatalog);
    },
    canEdit,
    baseFor,
    baseStatusFor,
    retryBase: (unitId) => {
      baseRequestedFor.current.delete(unitId);
      setBases((current) => {
        const next = { ...current };
        delete next[unitId];
        return next;
      });
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
      setEditor(blankStrategyDraft(units.map((unit) => unit.unitId)));
    },
    openEdit: (strategyId) => {
      const record = strategies.find((candidate) => candidate.strategy.strategy_id === strategyId);
      if (record === undefined || !canEdit) {
        return;
      }
      setPendingDeleteId(null);
      setFeedback(null);
      setEditor(
        draftFromStrategy(
          record,
          units.map((unit) => unit.unitId),
          nextRowKey,
        ),
      );
    },
    cancelEdit: () => {
      setEditor(null);
      setFeedback(null);
    },
    setName: (name) => editDraft((draft) => ({ ...draft, name })),
    setDescription: (description) => editDraft((draft) => ({ ...draft, description })),
    setCapitalStructureChoice: (choice) =>
      editDraft((draft) => {
        if (draft.capitalStructure.choice === choice) {
          return draft;
        }
        // The first switch to strategy-specific copies the Base structure, so
        // the analyst edits a real stack rather than building one from nothing
        // -- and every position keeps the id the Position matrix addresses it
        // by. A form already typed into is kept exactly as typed: returning to
        // Inherit Base and back does not discard the analyst's work.
        const form =
          choice === 'specific' && draft.capitalStructure.form.positions.length === 0
            ? formFromStructure(baseCapitalStructure)
            : draft.capitalStructure.form;
        return { ...draft, capitalStructure: { choice, form } };
      }),
    setCapitalStructure: (form) =>
      editDraft((draft) => ({ ...draft, capitalStructure: { ...draft.capitalStructure, form } })),
    setPartnershipChoice: (choice) =>
      editDraft((draft) => {
        if (draft.partnership.choice === choice) {
          return draft;
        }
        // The first switch to strategy-specific copies the Base Partnership, so
        // the analyst edits a real waterfall rather than building one from
        // nothing -- and every partner and tier keeps the id the Partner matrix
        // addresses it by. A form already typed into is kept exactly as typed:
        // moving between the three choices does not discard the analyst's work.
        //
        // With no Base Partnership to copy there is nothing to prefill, and the
        // analyst authors one from scratch; the copy invents nothing.
        const form =
          choice === 'specific' &&
          draft.partnership.form.partners.length === 0 &&
          basePartnership !== null
            ? formFromPartnership(basePartnership)
            : draft.partnership.form;
        return { ...draft, partnership: { choice, form } };
      }),
    setPartnership: (form) =>
      editDraft((draft) => ({ ...draft, partnership: { ...draft.partnership, form } })),
    setAcquisitionEnabled: (unitId, enabled) => enableFromBase(unitId, 'acquisition', enabled),
    setAcquisitionField: (unitId, field, value) =>
      editUnit(unitId, (unit) => ({ ...unit, acquisition: { ...unit.acquisition, [field]: value } })),
    setFinancingEnabled: (unitId, enabled) => enableFromBase(unitId, 'financing', enabled),
    setFinancingField: (unitId, field, value) =>
      editUnit(unitId, (unit) => ({ ...unit, financing: { ...unit.financing, [field]: value } })),
    setBusinessPlanChoice: (unitId, choice) => {
      const base = baseFor(unitId);
      editUnit(unitId, (unit) => {
        // Inherit Base -> Custom starts from a copy of this Unit's current Base
        // plan, for convenience, so it waits until that plan is here. Once
        // saved it is the Strategy's own, independent plan. No Business Plan
        // is an explicit empty plan and needs no Base.
        if (choice === 'custom' && domainNeedsBase(unit, 'business_plan')) {
          return base === null
            ? unit
            : { ...unit, businessPlan: { choice, plan: businessPlanDraftFromInput(base.businessPlan) } };
        }
        return { ...unit, businessPlan: { choice, plan: unit.businessPlan.plan } };
      });
    },
    setBusinessPlan: (unitId, plan) => {
      editUnit(unitId, (unit) => ({ ...unit, businessPlan: { ...unit.businessPlan, plan } }));
      // A refusal describes the plan that was sent; after an edit it may no
      // longer be true, so this Unit's row markings are cleared.
      setFeedback((current) => {
        const share = current?.byUnit[unitId];
        return current === null || share === undefined
          ? current
          : { ...current, byUnit: { ...current.byUnit, [unitId]: { ...share, planIssues: [] } } };
      });
    },
    setOutcomeEnabled: (unitId, enabled) =>
      editUnit(unitId, (unit) => ({
        ...unit,
        operatingOutcome: {
          enabled,
          rows: enabled && unit.operatingOutcome.rows.length === 0 ? [blankRow()] : unit.operatingOutcome.rows,
        },
      })),
    addOutcomeRow: (unitId) =>
      editUnit(unitId, (unit) => ({
        ...unit,
        operatingOutcome: { ...unit.operatingOutcome, rows: [...unit.operatingOutcome.rows, blankRow()] },
      })),
    removeOutcomeRow: (unitId, key) =>
      editUnit(unitId, (unit) => ({
        ...unit,
        operatingOutcome: {
          ...unit.operatingOutcome,
          rows: unit.operatingOutcome.rows.filter((row) => row.key !== key),
        },
      })),
    // A new target can change the units a value is typed in, so the typed
    // value is cleared rather than reinterpreted.
    setOutcomeTarget: (unitId, key, target) =>
      updateRow(unitId, key, (row) => (row.target === target ? row : { ...row, target, value: '' })),
    setOutcomeValue: (unitId, key, value) => updateRow(unitId, key, (row) => ({ ...row, value })),
    setDispositionEnabled: (unitId, enabled) => enableFromBase(unitId, 'disposition', enabled),
    setHoldPeriod: (unitId, value) =>
      editUnit(unitId, (unit) => ({ ...unit, disposition: { ...unit.disposition, holdPeriod: value } })),
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
