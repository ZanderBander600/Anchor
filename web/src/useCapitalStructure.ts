/**
 * Phase 7 Gate P7.8B -- the Base Capital Structure state of one open Deal, or
 * of one visible Investment.
 *
 * One hook per decision scope: it loads the saved structure, holds the
 * analyst's draft, saves it whole, and runs the structured analysis. It
 * computes no financial figure -- every funded amount, return, attachment,
 * coverage, Funding Requirement and Common Equity figure comes from the
 * backend (P-5).
 *
 * **One owner.** A Capital Structure belongs to an Investment. A standalone
 * Deal reaches its own through the Deal route, which materializes the hidden
 * one-unit Investment on the first non-empty save (Q4); the UI keeps saying
 * "Deal".
 *
 * **Whole-structure replacement.** The draft is the whole stack, saved in one
 * request. A refused save leaves the saved structure exactly as it was, and its
 * issues are kept so the editor can show them against the position they name.
 *
 * **Downstream staleness only.** A Capital Structure edit invalidates the
 * structured analysis and nothing upstream: the Project results and the Project
 * Decision Matrix stay as current as they were (P-4). The analysis is stale
 * when the saved base underwriting moved, when the saved structure moved, or
 * while there are unsaved edits -- and is simply absent until it is run.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  CapitalStructureError,
  analyzeStructuredVariant,
  readDealCapitalStructure,
  readInvestmentCapitalStructure,
  saveDealCapitalStructure,
  saveInvestmentCapitalStructure,
} from './api';
import { formFromStructure, structureFromForm } from './capitalStructureForm';
import type { CapitalStructureForm } from './capitalStructureForm';
import type {
  CapitalStructure,
  CapitalStructureIssue,
  StructuredVariantAnalysis,
} from './capitalTypes';

/** The reserved implicit Base keys: the Base Capital Structure is analysed on
 * the Base Strategy under the Base Scenario. */
const BASE = 'base';

export const EMPTY_CAPITAL_STRUCTURE: CapitalStructure = { positions: [] };

export interface UseCapitalStructureOptions {
  /** The open Deal, for a Deal-scoped workspace; `null` for an Investment. */
  dealId: string | null;
  /** The visible Investment, when the workspace is the Investment's. */
  investmentId?: string | null;
  /** Whether the base underwriting (or the Investment) has unsaved edits. */
  isDirty: boolean;
  /** The saved state the underwriting is at. A new save moves it. */
  savedAt: string | null;
  /** Whether the workspace is on screen. Nothing is requested before it is. */
  isActive: boolean;
}

export type LoadStatus = 'idle' | 'loading' | 'ready' | 'error';

export interface CapitalStructureState {
  /** The structure as saved. The empty structure means none is authored. */
  saved: CapitalStructure;
  /** The analyst's unsaved draft as the editor holds it -- every field a
   * string -- or `null` when the editor is closed. The contract is built from
   * it once, on save, so a half-typed number is never committed as a different
   * one. */
  draft: CapitalStructureForm | null;
  /** The saved structure the results describe. The editor edits `draft`. */
  shown: CapitalStructure;
  /** The Investment that owns it, once one exists. */
  investmentId: string | null;
  listStatus: LoadStatus;
  loadError: string | null;
  isSaving: boolean;
  saveError: string | null;
  /** The backend's own issues from the last refused save. */
  saveIssues: CapitalStructureIssue[];
  hasDraft: boolean;
  isDirtyDraft: boolean;
  analysis: StructuredVariantAnalysis | null;
  analysisError: string | null;
  analysisIssues: CapitalStructureIssue[];
  isAnalyzing: boolean;
  /** The analysis was produced from exactly the saved state on screen. */
  isAnalysisCurrent: boolean;
  canSave: boolean;
  canAnalyze: boolean;
  edit: () => void;
  change: (form: CapitalStructureForm) => void;
  cancel: () => void;
  save: () => Promise<void>;
  analyze: () => Promise<void>;
  retryLoad: () => void;
}

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function issuesOf(error: unknown): CapitalStructureIssue[] {
  return error instanceof CapitalStructureError ? error.issues : [];
}

export function useCapitalStructure({
  dealId,
  investmentId = null,
  isDirty,
  savedAt,
  isActive,
}: UseCapitalStructureOptions): CapitalStructureState {
  const [saved, setSaved] = useState<CapitalStructure>(EMPTY_CAPITAL_STRUCTURE);
  const [owner, setOwner] = useState<string | null>(investmentId);
  const [draft, setDraft] = useState<CapitalStructureForm | null>(null);
  const [listStatus, setListStatus] = useState<LoadStatus>('idle');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveIssues, setSaveIssues] = useState<CapitalStructureIssue[]>([]);
  const [analysis, setAnalysis] = useState<StructuredVariantAnalysis | null>(null);
  const [analysisToken, setAnalysisToken] = useState<string | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [analysisIssues, setAnalysisIssues] = useState<CapitalStructureIssue[]>([]);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  /** The latest request, so a slower earlier one can never overwrite it. */
  const activeLoad = useRef<object | null>(null);

  const scope = investmentId ?? dealId;

  /** The saved state an analysis belongs to: the underwriting's save and the
   * saved structure's economics. A rename of nothing else moves it. */
  const savedToken = useMemo(
    () => JSON.stringify([scope, savedAt, saved.positions]),
    [scope, savedAt, saved],
  );

  useEffect(() => {
    if (!isActive || scope === null) {
      return;
    }
    const current = {};
    activeLoad.current = current;
    setListStatus('loading');
    setLoadError(null);
    const request =
      investmentId !== null
        ? readInvestmentCapitalStructure(investmentId).then((payload) => ({
            investment_id: payload.investment_id as string | null,
            capital_structure: payload.capital_structure,
          }))
        : readDealCapitalStructure(dealId as string);
    request
      .then((payload) => {
        if (activeLoad.current !== current) {
          return;
        }
        setSaved(payload.capital_structure);
        setOwner(payload.investment_id);
        setListStatus('ready');
      })
      .catch((error: unknown) => {
        if (activeLoad.current !== current) {
          return;
        }
        setLoadError(messageOf(error, 'The capital structure could not be loaded.'));
        setListStatus('error');
      });
  }, [isActive, scope, dealId, investmentId, reloadKey]);

  const edit = useCallback(() => {
    setDraft((open) => open ?? formFromStructure(saved));
    setSaveError(null);
    setSaveIssues([]);
  }, [saved]);

  const change = useCallback((form: CapitalStructureForm) => {
    setDraft(form);
  }, []);

  const cancel = useCallback(() => {
    setDraft(null);
    setSaveError(null);
    setSaveIssues([]);
  }, []);

  const isDirtyDraft =
    draft !== null &&
    JSON.stringify(draft.positions) !== JSON.stringify(formFromStructure(saved).positions);
  const canSave = draft !== null && !isSaving && !isDirty && scope !== null;

  const save = useCallback(async () => {
    if (draft === null || isSaving || isDirty || scope === null) {
      return;
    }
    setSaveError(null);
    setSaveIssues([]);
    let structure: CapitalStructure;
    try {
      // The one conversion from what the analyst typed to the contract. A
      // blank or unparsable number is refused here, by field name, before any
      // request is made -- exactly as the assumption form refuses one. Every
      // domain rule stays the backend's.
      structure = structureFromForm(draft);
    } catch (error: unknown) {
      setSaveError(messageOf(error, 'The capital structure could not be saved.'));
      return;
    }
    setIsSaving(true);
    try {
      const payload =
        investmentId !== null
          ? await saveInvestmentCapitalStructure(investmentId, structure)
          : await saveDealCapitalStructure(dealId as string, structure);
      setSaved(payload.capital_structure);
      setOwner(
        'investment_id' in payload ? (payload.investment_id as string | null) : investmentId,
      );
      setDraft(null);
      // The saved structure moved, so any analysis on screen describes an
      // older stack. It is kept visible and marked stale, never silently
      // reused as current.
      setAnalysisToken(null);
    } catch (error: unknown) {
      setSaveError(messageOf(error, 'The capital structure could not be saved.'));
      setSaveIssues(issuesOf(error));
    } finally {
      setIsSaving(false);
    }
  }, [draft, isSaving, isDirty, scope, investmentId, dealId]);

  const canAnalyze = owner !== null && !isDirty && !isAnalyzing && listStatus === 'ready';

  const analyze = useCallback(async () => {
    if (owner === null || isDirty || isAnalyzing) {
      return;
    }
    setIsAnalyzing(true);
    setAnalysisError(null);
    setAnalysisIssues([]);
    const ranAgainst = savedToken;
    try {
      const report = await analyzeStructuredVariant(owner, BASE, BASE);
      setAnalysis(report);
      setAnalysisToken(ranAgainst);
    } catch (error: unknown) {
      setAnalysisError(messageOf(error, 'The capital structure analysis could not be completed.'));
      setAnalysisIssues(issuesOf(error));
    } finally {
      setIsAnalyzing(false);
    }
  }, [owner, isDirty, isAnalyzing, savedToken]);

  const retryLoad = useCallback(() => {
    setReloadKey((key) => key + 1);
  }, []);

  return {
    saved,
    draft,
    shown: saved,
    investmentId: owner,
    listStatus,
    loadError,
    isSaving,
    saveError,
    saveIssues,
    hasDraft: draft !== null,
    isDirtyDraft,
    analysis,
    analysisError,
    analysisIssues,
    isAnalyzing,
    isAnalysisCurrent: analysis !== null && analysisToken === savedToken && !isDirty,
    canSave,
    canAnalyze,
    edit,
    change,
    cancel,
    save,
    analyze,
    retryLoad,
  };
}
