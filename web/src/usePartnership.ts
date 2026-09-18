/**
 * Phase 7 Gate P7.9 Stage 3 -- the Base Partnership state of one open Deal, or
 * of one visible Investment.
 *
 * One hook per decision scope: it loads the saved Partnership, holds the
 * analyst's draft, saves it whole, and runs the Partnership analysis. It
 * computes no financial figure -- every contribution, distribution, IRR, MOIC,
 * profit, distribution difference, Promote Earned, benchmark capital
 * subordination and tier attribution comes from the accepted Stage 1 engine
 * (P-5).
 *
 * **One owner, two doors.** A Partnership belongs to an Investment. A standalone
 * Deal reaches its own through the Deal route, which materializes the hidden
 * one-unit Investment on the first save; the UI keeps saying "Deal".
 *
 * **Opt-in.** `null` is the ordinary state: most Deals have no Partnership, and
 * the workspace shows an empty state and an Add action rather than waterfall
 * controls nobody asked for. Clearing one saves `null`, the explicit "no
 * Partnership" -- never an empty contract, because a Partnership always has at
 * least one partner and so cannot be empty.
 *
 * **Downstream staleness only (P-4).** A Partnership edit invalidates the
 * Partnership result and the Partner matrix, and nothing else: the Project
 * results, the structured Capital Structure results and their two matrices stay
 * exactly as current as they were, because neither of their cell identities
 * includes a Partnership. The analysis is stale when the saved base underwriting
 * moved, when the saved Partnership moved, or while there are unsaved edits --
 * and is simply absent until it is run. A stale analysis stays on screen, marked
 * out of date; it is never silently presented as current.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  PartnershipError,
  analyzePartnershipVariant,
  readDealPartnership,
  readInvestmentPartnership,
  saveDealPartnership,
  saveInvestmentPartnership,
} from './api';
import {
  EMPTY_PARTNERSHIP_FORM,
  formFromPartnership,
  partnershipFromForm,
} from './partnershipForm';
import type { PartnershipForm } from './partnershipForm';
import type {
  Partnership,
  PartnershipIssue,
  PartnershipVariantAnalysis,
} from './partnershipTypes';

/** The reserved implicit Base keys: the Base Partnership is analysed on the
 * Base Strategy under the Base Scenario. */
const BASE = 'base';

export interface UsePartnershipOptions {
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

export type PartnershipLoadStatus = 'idle' | 'loading' | 'ready' | 'error';

export interface PartnershipState {
  /** The Partnership as saved, or `null` when this owner states none. */
  saved: Partnership | null;
  /** The analyst's unsaved draft as the editor holds it -- every field a
   * string -- or `null` when the editor is closed. The contract is built from
   * it once, on save, so a half-typed number is never committed as a different
   * one. */
  draft: PartnershipForm | null;
  /** The Investment that owns it, once one exists. */
  investmentId: string | null;
  listStatus: PartnershipLoadStatus;
  loadError: string | null;
  isSaving: boolean;
  saveError: string | null;
  /** The backend's own issues from the last refused save. */
  saveIssues: PartnershipIssue[];
  hasDraft: boolean;
  isDirtyDraft: boolean;
  analysis: PartnershipVariantAnalysis | null;
  analysisError: string | null;
  analysisIssues: PartnershipIssue[];
  isAnalyzing: boolean;
  /** The analysis was produced from exactly the saved state on screen. A
   * `false` with an analysis present is a *stale* analysis, which stays
   * visible and is labelled as out of date. */
  isAnalysisCurrent: boolean;
  canSave: boolean;
  canAnalyze: boolean;
  /** Open the editor on the saved Partnership. */
  edit: () => void;
  /** Open the editor on a brand-new Partnership, with nothing stated. */
  add: () => void;
  change: (form: PartnershipForm) => void;
  cancel: () => void;
  save: () => Promise<void>;
  /** Save the explicit "no Partnership", clearing the saved one. */
  remove: () => Promise<void>;
  analyze: () => Promise<void>;
  retryLoad: () => void;
}

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function issuesOf(error: unknown): PartnershipIssue[] {
  return error instanceof PartnershipError ? error.issues : [];
}

const LOAD_FAILED = 'The partnership could not be loaded.';
const SAVE_FAILED = 'The partnership could not be saved.';
const ANALYSIS_FAILED = 'The partnership analysis could not be completed.';

export function usePartnership({
  dealId,
  investmentId = null,
  isDirty,
  savedAt,
  isActive,
}: UsePartnershipOptions): PartnershipState {
  const [saved, setSaved] = useState<Partnership | null>(null);
  const [owner, setOwner] = useState<string | null>(investmentId);
  const [draft, setDraft] = useState<PartnershipForm | null>(null);
  const [listStatus, setListStatus] = useState<PartnershipLoadStatus>('idle');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveIssues, setSaveIssues] = useState<PartnershipIssue[]>([]);
  const [analysis, setAnalysis] = useState<PartnershipVariantAnalysis | null>(null);
  const [analysisToken, setAnalysisToken] = useState<string | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [analysisIssues, setAnalysisIssues] = useState<PartnershipIssue[]>([]);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  /** The latest request, so a slower earlier one can never overwrite it. */
  const activeLoad = useRef<object | null>(null);

  const scope = investmentId ?? dealId;

  /** The saved state an analysis belongs to: the underwriting's save and the
   * saved Partnership's whole statement. A name is part of the saved contract
   * and so moves it; nothing here decides what is *economic*, which is the
   * backend fingerprint's judgement, not this token's. */
  const savedToken = useMemo(
    () => JSON.stringify([scope, savedAt, saved]),
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
        ? readInvestmentPartnership(investmentId).then((payload) => ({
            investment_id: payload.investment_id as string | null,
            partnership: payload.partnership,
          }))
        : readDealPartnership(dealId as string);
    request
      .then((payload) => {
        if (activeLoad.current !== current) {
          return;
        }
        setSaved(payload.partnership);
        setOwner(payload.investment_id);
        setListStatus('ready');
      })
      .catch((error: unknown) => {
        if (activeLoad.current !== current) {
          return;
        }
        setLoadError(messageOf(error, LOAD_FAILED));
        setListStatus('error');
      });
  }, [isActive, scope, dealId, investmentId, reloadKey]);

  const edit = useCallback(() => {
    setDraft((open) => open ?? (saved === null ? EMPTY_PARTNERSHIP_FORM : formFromPartnership(saved)));
    setSaveError(null);
    setSaveIssues([]);
  }, [saved]);

  const add = useCallback(() => {
    setDraft((open) => open ?? EMPTY_PARTNERSHIP_FORM);
    setSaveError(null);
    setSaveIssues([]);
  }, []);

  const change = useCallback((form: PartnershipForm) => {
    setDraft(form);
  }, []);

  const cancel = useCallback(() => {
    setDraft(null);
    setSaveError(null);
    setSaveIssues([]);
  }, []);

  /** The draft as the editor would hold the saved Partnership: the comparison
   * both `isDirtyDraft` and a leave warning are made against. */
  const savedAsForm = useMemo(
    () => (saved === null ? EMPTY_PARTNERSHIP_FORM : formFromPartnership(saved)),
    [saved],
  );

  const isDirtyDraft = draft !== null && JSON.stringify(draft) !== JSON.stringify(savedAsForm);
  const canSave = draft !== null && !isSaving && !isDirty && scope !== null;

  /** One save of one whole statement: an authored Partnership, or `null`. */
  const put = useCallback(
    async (partnership: Partnership | null) => {
      const payload =
        investmentId !== null
          ? await saveInvestmentPartnership(investmentId, partnership)
          : await saveDealPartnership(dealId as string, partnership);
      setSaved(payload.partnership);
      setOwner('investment_id' in payload ? (payload.investment_id as string | null) : investmentId);
      setDraft(null);
      // The saved Partnership moved, so any analysis on screen describes an
      // older one. It is kept visible and marked stale, never silently reused
      // as current.
      setAnalysisToken(null);
    },
    [investmentId, dealId],
  );

  const save = useCallback(async () => {
    if (draft === null || isSaving || isDirty || scope === null) {
      return;
    }
    setSaveError(null);
    setSaveIssues([]);
    let partnership: Partnership;
    try {
      // The one conversion from what the analyst typed to the contract. A
      // blank number, an unparsable one, or a choice that has not been stated
      // is refused here, by name, before any request is made. Every domain
      // rule stays the Stage 1 validator's.
      partnership = partnershipFromForm(draft);
    } catch (error: unknown) {
      setSaveError(messageOf(error, SAVE_FAILED));
      return;
    }
    setIsSaving(true);
    try {
      await put(partnership);
    } catch (error: unknown) {
      setSaveError(messageOf(error, SAVE_FAILED));
      setSaveIssues(issuesOf(error));
    } finally {
      setIsSaving(false);
    }
  }, [draft, isSaving, isDirty, scope, put]);

  const remove = useCallback(async () => {
    if (isSaving || isDirty || scope === null) {
      return;
    }
    setSaveError(null);
    setSaveIssues([]);
    setIsSaving(true);
    try {
      await put(null);
    } catch (error: unknown) {
      setSaveError(messageOf(error, SAVE_FAILED));
      setSaveIssues(issuesOf(error));
    } finally {
      setIsSaving(false);
    }
  }, [isSaving, isDirty, scope, put]);

  // Nothing to analyse until a Partnership is saved: a variant with none has no
  // Partnership result and no Partnership fingerprint (FP-2), so the product
  // asks for neither.
  const canAnalyze =
    owner !== null && saved !== null && !isDirty && !isAnalyzing && listStatus === 'ready';

  const analyze = useCallback(async () => {
    if (owner === null || saved === null || isDirty || isAnalyzing) {
      return;
    }
    setIsAnalyzing(true);
    setAnalysisError(null);
    setAnalysisIssues([]);
    const ranAgainst = savedToken;
    try {
      const report = await analyzePartnershipVariant(owner, BASE, BASE);
      setAnalysis(report);
      setAnalysisToken(ranAgainst);
    } catch (error: unknown) {
      setAnalysisError(messageOf(error, ANALYSIS_FAILED));
      setAnalysisIssues(issuesOf(error));
    } finally {
      setIsAnalyzing(false);
    }
  }, [owner, saved, isDirty, isAnalyzing, savedToken]);

  const retryLoad = useCallback(() => {
    setReloadKey((key) => key + 1);
  }, []);

  return {
    saved,
    draft,
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
    add,
    change,
    cancel,
    save,
    remove,
    analyze,
    retryLoad,
  };
}
