/**
 * Phase 7 Gate P7.10 Stage 4 -- the Investment Memo workspace's state.
 *
 * One hook owns the memo draft, its sources, its valuation views, its
 * publication readiness, its published versions and each version's committee
 * decision. It is transport and state; it computes no financial value and
 * formats none.
 *
 * **The draft is never lost silently.** Edits live here until an explicit Save.
 * `isDirty` compares what would be sent against what was last saved, the
 * workspace reports it, and leaving is guarded by the caller. A failed save
 * leaves the edits exactly where they were -- nothing is rolled back to the
 * server's copy behind the analyst's back.
 *
 * **A stale error clears when its cause changes.** A save error, a publication
 * refusal and an export refusal are each cleared the moment the analyst edits
 * the thing they concern, so no panel keeps showing a complaint about state
 * that no longer exists.
 *
 * **Publishing is a separate act with its own prerequisites.** Readiness is
 * read from the backend, never guessed here: the product disables publication
 * with the backend's own typed reasons rather than a client-side rule that
 * could disagree with the one that actually refuses.
 *
 * **Stage 4 ships no AI.** No proposal, prompt, grounding or AI state exists in
 * this hook. Stage 3 is deferred and unstarted.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  EvidenceInUseError,
  MemoError,
  listInvestmentScenarios,
  listInvestmentStrategies,
  listPartnerPerspectives,
  listPositionPerspectives,
  PublicationRefusedError,
  deleteEvidenceReference,
  publishInvestmentMemo,
  readCommitteeDecision,
  readEvidenceReferences,
  readInvestmentMemo,
  readMemoVersionFreshness,
  readMemoVersions,
  readPublicationReadiness,
  readValuationTimepoints,
  readValuationViews,
  saveCommitteeDecision,
  saveEvidenceReference,
  saveInvestmentMemo,
} from './api';
import {
  EMPTY_MEMO_FORM,
  isMemoFormDirty,
  memoFormFromDraft,
  memoRequestFromForm,
} from './memoForm';
import type { MemoDraftForm } from './memoForm';
import {
  BASE_SCENARIO_KEY,
  BASE_SCENARIO_NAME,
  BASE_STRATEGY_KEY,
  BASE_STRATEGY_NAME,
} from './memoCatalog';
import type {
  InvestmentCommitteeDecision,
  InvestmentCommitteeOutcome,
  InvestmentMemoVersion,
  MemoEvidenceReference,
  MemoFreshnessReport,
  MemoIssue,
  PublicationRefusal,
  ValuationSurface,
  ValuationTimepoint,
} from './memoTypes';

export type MemoLoadStatus = 'loading' | 'ready' | 'error';
export type MemoSaveStatus = 'idle' | 'saving' | 'saved' | 'error';

export interface UseInvestmentMemoOptions {
  investmentId: string;
  /** A new object re-reads the memo and everything around it. */
  refreshSignal?: object;
  /** Whether the workspace is on screen. While hidden it requests nothing, so
   * a mounted-but-hidden memo never competes with the surface in front of the
   * analyst. */
  isActive?: boolean;
}

export interface UseInvestmentMemoResult {
  status: MemoLoadStatus;
  loadError: string | null;
  retryLoad: () => void;

  form: MemoDraftForm;
  setForm: (next: MemoDraftForm | ((current: MemoDraftForm) => MemoDraftForm)) => void;
  isDirty: boolean;
  hasSavedDraft: boolean;

  saveStatus: MemoSaveStatus;
  saveError: string | null;
  saveIssues: MemoIssue[];
  save: () => Promise<boolean>;

  evidence: MemoEvidenceReference[];
  saveEvidence: (reference: MemoEvidenceReference) => Promise<boolean>;
  removeEvidence: (evidenceId: string) => Promise<boolean>;
  evidenceError: string | null;
  evidenceInUse: EvidenceInUseError | null;
  clearEvidenceError: () => void;

  timepoints: ValuationTimepoint[];
  surface: ValuationSurface | null;
  surfaceError: string | null;
  isSurfaceLoading: boolean;

  readiness: { publishable: boolean; refusals: PublicationRefusal[] } | null;
  isReadinessLoading: boolean;
  refreshReadiness: () => Promise<void>;

  publish: () => Promise<InvestmentMemoVersion | null>;
  isPublishing: boolean;
  publishRefusals: PublicationRefusal[];
  publishError: string | null;
  clearPublishError: () => void;

  versions: InvestmentMemoVersion[];
  freshness: Record<string, MemoFreshnessReport>;
  loadFreshness: (versionId: string) => Promise<void>;

  decisions: Record<string, InvestmentCommitteeDecision | null>;
  loadDecision: (versionId: string) => Promise<void>;
  recordDecision: (
    versionId: string,
    decision: InvestmentCommitteeOutcome,
    note: string,
  ) => Promise<boolean>;
  decisionError: string | null;
  isRecordingDecision: boolean;
}

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error && error.message !== '' ? error.message : fallback;
}

export function useInvestmentMemo({
  investmentId,
  refreshSignal,
  isActive = true,
}: UseInvestmentMemoOptions): UseInvestmentMemoResult {
  const [status, setStatus] = useState<MemoLoadStatus>('loading');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState({});

  const [form, setFormState] = useState<MemoDraftForm>(EMPTY_MEMO_FORM);
  const [saved, setSaved] = useState<MemoDraftForm | null>(null);
  const [saveStatus, setSaveStatus] = useState<MemoSaveStatus>('idle');
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveIssues, setSaveIssues] = useState<MemoIssue[]>([]);

  const [evidence, setEvidence] = useState<MemoEvidenceReference[]>([]);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [evidenceInUse, setEvidenceInUse] = useState<EvidenceInUseError | null>(null);

  const [timepoints, setTimepoints] = useState<ValuationTimepoint[]>([]);
  const [surface, setSurface] = useState<ValuationSurface | null>(null);
  const [surfaceError, setSurfaceError] = useState<string | null>(null);
  const [isSurfaceLoading, setIsSurfaceLoading] = useState(false);

  const [readiness, setReadiness] = useState<{
    publishable: boolean;
    refusals: PublicationRefusal[];
  } | null>(null);
  const [isReadinessLoading, setIsReadinessLoading] = useState(false);

  const [isPublishing, setIsPublishing] = useState(false);
  const [publishRefusals, setPublishRefusals] = useState<PublicationRefusal[]>([]);
  const [publishError, setPublishError] = useState<string | null>(null);

  const [versions, setVersions] = useState<InvestmentMemoVersion[]>([]);
  const [freshness, setFreshness] = useState<Record<string, MemoFreshnessReport>>({});
  const [decisions, setDecisions] = useState<
    Record<string, InvestmentCommitteeDecision | null>
  >({});
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [isRecordingDecision, setIsRecordingDecision] = useState(false);

  /** Guards every async settle: a response that arrives after the workspace
   * moved to another Investment, or unmounted, is discarded rather than written
   * into state that no longer belongs to it. */
  const liveRef = useRef(true);
  useEffect(() => {
    liveRef.current = true;
    return () => {
      liveRef.current = false;
    };
  }, []);

  /**
   * Editing clears the complaints that edit could have fixed.
   *
   * A publication refusal describes the draft as it was when the check ran, so
   * the moment the analyst changes the draft it is no longer a statement about
   * what they are looking at. Keeping it on screen would ask them to satisfy a
   * rule against state that no longer exists.
   */
  const setForm = useCallback(
    (next: MemoDraftForm | ((current: MemoDraftForm) => MemoDraftForm)) => {
      setFormState((current) => (typeof next === 'function' ? next(current) : next));
      setSaveStatus((current) => (current === 'saved' ? 'idle' : current));
      setSaveError(null);
      setSaveIssues([]);
      setPublishRefusals([]);
      setPublishError(null);
    },
    [],
  );

  const loadAll = useCallback(async () => {
    setStatus('loading');
    setLoadError(null);
    try {
      const [draft, references, definitions, published] = await Promise.all([
        readInvestmentMemo(investmentId),
        readEvidenceReferences(investmentId),
        readValuationTimepoints(investmentId),
        readMemoVersions(investmentId),
      ]);
      if (!liveRef.current) {
        return;
      }
      const loaded = draft === null ? EMPTY_MEMO_FORM : memoFormFromDraft(draft);
      setFormState(loaded);
      setSaved(draft === null ? null : loaded);
      setEvidence(references);
      setTimepoints(definitions);
      setVersions(published);
      setStatus('ready');
    } catch (error) {
      if (!liveRef.current) {
        return;
      }
      setLoadError(messageOf(error, 'The memo could not be loaded.'));
      setStatus('error');
    }
  }, [investmentId]);

  useEffect(() => {
    if (!isActive) {
      return;
    }
    void loadAll();
  }, [loadAll, isActive, refreshSignal, reloadToken]);

  const retryLoad = useCallback(() => setReloadToken({}), []);

  const isDirty = useMemo(() => isMemoFormDirty(form, saved), [form, saved]);
  const hasSavedDraft = saved !== null;

  const save = useCallback(async (): Promise<boolean> => {
    setSaveStatus('saving');
    setSaveError(null);
    setSaveIssues([]);
    try {
      const result = await saveInvestmentMemo(investmentId, memoRequestFromForm(form));
      if (!liveRef.current) {
        return true;
      }
      // The server's copy becomes the saved baseline, but the analyst's edits
      // are not replaced by it: what they typed stays on screen.
      setSaved(memoFormFromDraft(result));
      setSaveStatus('saved');
      return true;
    } catch (error) {
      if (!liveRef.current) {
        return false;
      }
      setSaveStatus('error');
      setSaveError(messageOf(error, 'The memo could not be saved.'));
      setSaveIssues(error instanceof MemoError ? error.issues : []);
      return false;
    }
  }, [form, investmentId]);

  const clearEvidenceError = useCallback(() => {
    setEvidenceError(null);
    setEvidenceInUse(null);
  }, []);

  const saveEvidenceReferenceFor = useCallback(
    async (reference: MemoEvidenceReference): Promise<boolean> => {
      clearEvidenceError();
      try {
        const result = await saveEvidenceReference(investmentId, reference);
        if (!liveRef.current) {
          return true;
        }
        setEvidence((current) => {
          const without = current.filter((item) => item.evidence_id !== result.evidence_id);
          return [...without, result].sort(
            (left, right) => left.display_order - right.display_order,
          );
        });
        return true;
      } catch (error) {
        if (!liveRef.current) {
          return false;
        }
        setEvidenceError(messageOf(error, 'The source could not be saved.'));
        return false;
      }
    },
    [clearEvidenceError, investmentId],
  );

  const removeEvidence = useCallback(
    async (evidenceId: string): Promise<boolean> => {
      clearEvidenceError();
      try {
        await deleteEvidenceReference(investmentId, evidenceId);
        if (!liveRef.current) {
          return true;
        }
        setEvidence((current) => current.filter((item) => item.evidence_id !== evidenceId));
        return true;
      } catch (error) {
        if (!liveRef.current) {
          return false;
        }
        // A source something still cites is its own conflict, with what to
        // detach. Never cascaded: removing it would leave a claim, or an
        // analyst-supplied valuation, pointing at nothing.
        if (error instanceof EvidenceInUseError) {
          setEvidenceInUse(error);
        }
        setEvidenceError(messageOf(error, 'The source could not be removed.'));
        return false;
      }
    },
    [clearEvidenceError, investmentId],
  );

  // The valuation surface follows the selected cell: resolving views needs a
  // Strategy and a Scenario, and a draft that has not chosen one has nothing to
  // resolve against. That is a real state, not an error.
  const strategyId = form.selectedDecision?.strategy_id ?? null;
  const scenarioId = form.selectedDecision?.scenario_id ?? null;

  useEffect(() => {
    if (!isActive || status !== 'ready' || strategyId === null || scenarioId === null) {
      return;
    }
    let cancelled = false;
    setIsSurfaceLoading(true);
    setSurfaceError(null);
    void readValuationViews(investmentId, strategyId, scenarioId)
      .then((result) => {
        if (cancelled || !liveRef.current) {
          return;
        }
        setSurface(result);
      })
      .catch((error: unknown) => {
        if (cancelled || !liveRef.current) {
          return;
        }
        setSurface(null);
        setSurfaceError(messageOf(error, 'The valuation views could not be resolved.'));
      })
      .finally(() => {
        if (!cancelled && liveRef.current) {
          setIsSurfaceLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [investmentId, strategyId, scenarioId, isActive, status, timepoints]);

  const refreshReadiness = useCallback(async () => {
    if (!hasSavedDraft) {
      return;
    }
    setIsReadinessLoading(true);
    try {
      const result = await readPublicationReadiness(investmentId);
      if (!liveRef.current) {
        return;
      }
      setReadiness({ publishable: result.publishable, refusals: result.refusals });
    } catch {
      if (liveRef.current) {
        setReadiness(null);
      }
    } finally {
      if (liveRef.current) {
        setIsReadinessLoading(false);
      }
    }
  }, [hasSavedDraft, investmentId]);

  const clearPublishError = useCallback(() => {
    setPublishRefusals([]);
    setPublishError(null);
  }, []);

  const publish = useCallback(async (): Promise<InvestmentMemoVersion | null> => {
    clearPublishError();
    setIsPublishing(true);
    try {
      const version = await publishInvestmentMemo(investmentId);
      if (!liveRef.current) {
        return version;
      }
      // Publishing never overwrites: the new version joins the history and the
      // draft is left exactly as it was.
      setVersions((current) => [...current, version]);
      await refreshReadiness();
      return version;
    } catch (error) {
      if (!liveRef.current) {
        return null;
      }
      if (error instanceof PublicationRefusedError) {
        setPublishRefusals(error.refusals);
      }
      setPublishError(messageOf(error, 'The memo could not be published.'));
      return null;
    } finally {
      if (liveRef.current) {
        setIsPublishing(false);
      }
    }
  }, [clearPublishError, investmentId, refreshReadiness]);

  const loadFreshness = useCallback(
    async (versionId: string) => {
      try {
        const report = await readMemoVersionFreshness(investmentId, versionId);
        if (liveRef.current) {
          setFreshness((current) => ({ ...current, [versionId]: report }));
        }
      } catch {
        // A freshness read that fails leaves the version readable and simply
        // unannotated; it never withholds or rewrites the published version.
      }
    },
    [investmentId],
  );

  const loadDecision = useCallback(
    async (versionId: string) => {
      try {
        const decision = await readCommitteeDecision(investmentId, versionId);
        if (liveRef.current) {
          setDecisions((current) => ({ ...current, [versionId]: decision }));
        }
      } catch {
        // Leave the row saying nothing is recorded rather than inventing one.
      }
    },
    [investmentId],
  );

  const recordDecision = useCallback(
    async (
      versionId: string,
      decision: InvestmentCommitteeOutcome,
      note: string,
    ): Promise<boolean> => {
      setDecisionError(null);
      setIsRecordingDecision(true);
      try {
        const saved = await saveCommitteeDecision(investmentId, versionId, {
          decision,
          decision_note: note.trim() === '' ? null : note,
          decided_at: null,
        });
        if (liveRef.current) {
          setDecisions((current) => ({ ...current, [versionId]: saved }));
        }
        return true;
      } catch (error) {
        if (liveRef.current) {
          setDecisionError(messageOf(error, 'The committee decision could not be saved.'));
        }
        return false;
      } finally {
        if (liveRef.current) {
          setIsRecordingDecision(false);
        }
      }
    },
    [investmentId],
  );

  return {
    status,
    loadError,
    retryLoad,
    form,
    setForm,
    isDirty,
    hasSavedDraft,
    saveStatus,
    saveError,
    saveIssues,
    save,
    evidence,
    saveEvidence: saveEvidenceReferenceFor,
    removeEvidence,
    evidenceError,
    evidenceInUse,
    clearEvidenceError,
    timepoints,
    surface,
    surfaceError,
    isSurfaceLoading,
    readiness,
    isReadinessLoading,
    refreshReadiness,
    publish,
    isPublishing,
    publishRefusals,
    publishError,
    clearPublishError,
    versions,
    freshness,
    loadFreshness,
    decisions,
    loadDecision,
    recordDecision,
    decisionError,
    isRecordingDecision,
  };
}

/**
 * The decision context a memo can select from: this Investment's Strategies,
 * Scenarios, capital positions and partners.
 *
 * Its own hook because it is read-only reference data with a different
 * lifetime from the draft: it changes when the analyst edits a Strategy
 * elsewhere, not when they type in the memo.
 *
 * Every list includes the reserved implicit Base key, so selecting "the Base
 * cell" is an ordinary choice rather than a missing one. A failed read leaves
 * the lists empty and the selector says so; it never invents a Strategy.
 */
export interface MemoDecisionContext {
  strategies: { id: string; name: string }[];
  scenarios: { id: string; name: string }[];
  positions: { id: string; name: string }[];
  partners: { id: string; name: string }[];
  isLoading: boolean;
  error: string | null;
}

export function useMemoDecisionContext(
  investmentId: string,
  isActive = true,
): MemoDecisionContext {
  const [context, setContext] = useState<MemoDecisionContext>({
    strategies: [],
    scenarios: [],
    positions: [],
    partners: [],
    isLoading: true,
    error: null,
  });

  useEffect(() => {
    if (!isActive) {
      return;
    }
    let cancelled = false;
    setContext((current) => ({ ...current, isLoading: true, error: null }));
    void Promise.all([
      listInvestmentStrategies(investmentId).catch(() => []),
      listInvestmentScenarios(investmentId).catch(() => []),
      listPositionPerspectives(investmentId).catch(() => null),
      listPartnerPerspectives(investmentId).catch(() => null),
    ])
      .then(([strategies, scenarios, positions, partners]) => {
        if (cancelled) {
          return;
        }
        setContext({
          strategies: [
            { id: BASE_STRATEGY_KEY, name: BASE_STRATEGY_NAME },
            ...strategies.map((entry) => ({
              id: entry.strategy.strategy_id,
              name: entry.strategy.name,
            })),
          ],
          scenarios: [
            { id: BASE_SCENARIO_KEY, name: BASE_SCENARIO_NAME },
            ...scenarios.map((entry) => ({
              id: entry.scenario.scenario_id,
              name: entry.scenario.name,
            })),
          ],
          // The common-equity marker is a residual, not an addressable
          // position, so it is not offered as a decision perspective.
          positions: (positions?.positions ?? [])
            .filter((position) => !position.is_common_equity_marker)
            .map((position) => ({ id: position.position_id, name: position.name })),
          partners: (partners?.partners ?? []).map((partner) => ({
            id: partner.partner_id,
            name: partner.name,
          })),
          isLoading: false,
          error: null,
        });
      })
      .catch(() => {
        if (!cancelled) {
          setContext((current) => ({
            ...current,
            isLoading: false,
            error: 'The decision context could not be loaded.',
          }));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [investmentId, isActive]);

  return context;
}
