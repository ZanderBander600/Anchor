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
import { messageOf, useAsyncResource } from './useAsyncResource';
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

/** Shared empties, so a loading render hands consumers the same identity each
 * time rather than a fresh array that invalidates their memoisation. */
const NO_EVIDENCE: MemoEvidenceReference[] = [];
const NO_TIMEPOINTS: ValuationTimepoint[] = [];
const NO_VERSIONS: InvestmentMemoVersion[] = [];
const NO_OPTIONS: { id: string; name: string }[] = [];

/** What the callbacks read when they need the current draft without taking a
 * dependency on it. */
interface LatestState {
  loadedForm: MemoDraftForm | null;
  evidence: MemoEvidenceReference[];
  form: MemoDraftForm;
}

export type MemoLoadStatus = 'loading' | 'ready' | 'error';
export type MemoSaveStatus = 'idle' | 'saving' | 'saved' | 'error';

export interface UseInvestmentMemoOptions {
  investmentId: string;
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

export function useInvestmentMemo({
  investmentId,
  isActive = true,
}: UseInvestmentMemoOptions): UseInvestmentMemoResult {
  const [form, setFormState] = useState<MemoDraftForm | null>(null);
  const [saved, setSaved] = useState<MemoDraftForm | null>(null);
  const [saveStatus, setSaveStatus] = useState<MemoSaveStatus>('idle');
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveIssues, setSaveIssues] = useState<MemoIssue[]>([]);

  const [evidenceEdits, setEvidenceEdits] = useState<MemoEvidenceReference[] | null>(null);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [evidenceInUse, setEvidenceInUse] = useState<EvidenceInUseError | null>(null);

  const [readiness, setReadiness] = useState<{
    publishable: boolean;
    refusals: PublicationRefusal[];
  } | null>(null);
  const [isReadinessLoading, setIsReadinessLoading] = useState(false);

  const [isPublishing, setIsPublishing] = useState(false);
  const [publishRefusals, setPublishRefusals] = useState<PublicationRefusal[]>([]);
  const [publishError, setPublishError] = useState<string | null>(null);

  const [publishedHere, setPublishedHere] = useState<InvestmentMemoVersion[]>([]);
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

  const latestRef = useRef<LatestState | null>(null);
  /** What the hook currently holds, for the callbacks that read it without
   * taking a dependency on it.
   *
   * Declared before its first use rather than beside the effect that fills it:
   * a callback closing over a `const` declared further down works at call time
   * but reads, to a linter and to a person, like a use-before-declaration.
   *
   * The ref starts at `null` and is *replaced* wholesale, never mutated field
   * by field, so the value handed to `useRef` is never modified -- which is
   * what `react(immutability)` asks for -- and two of its three fields can
   * never momentarily disagree. */
  const latest = (): LatestState =>
    latestRef.current ?? { loadedForm: null, evidence: NO_EVIDENCE, form: EMPTY_MEMO_FORM };

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
      // Seeded from the loaded draft on the first edit: `form` is `null` until
      // the analyst touches something, so the loaded draft shows through
      // without an effect copying it into state.
      setFormState((current) => {
        const base = current ?? latest().loadedForm ?? EMPTY_MEMO_FORM;
        return typeof next === 'function' ? next(base) : next;
      });
      setSaveStatus((current) => (current === 'saved' ? 'idle' : current));
      setSaveError(null);
      setSaveIssues([]);
      setPublishRefusals([]);
      setPublishError(null);
    },
    [],
  );

  /** The memo and everything around it, read in one pass.
   *
   * One resource rather than four, because the workspace has nothing useful to
   * show until all four have landed: a draft without its sources cannot render
   * a claim's citations, and a half-loaded memo would flicker through states no
   * analyst needs to see. */
  const loadMemo = useCallback(async () => {
    const [draft, references, definitions, published] = await Promise.all([
      readInvestmentMemo(investmentId),
      readEvidenceReferences(investmentId),
      readValuationTimepoints(investmentId),
      readMemoVersions(investmentId),
    ]);
    return { draft, references, definitions, published };
  }, [investmentId]);

  const loaded = useAsyncResource(
    isActive ? investmentId : null,
    loadMemo,
    'The memo could not be loaded.',
  );

  const status: MemoLoadStatus =
    loaded.status === 'ready' ? 'ready' : loaded.status === 'error' ? 'error' : 'loading';

  /** The draft as loaded, and the analyst's edits layered over it.
   *
   * `form` is `null` until the analyst has touched something, so the loaded
   * draft shows through without an effect copying it into state. That copy is
   * what made this hook set state while loading; deriving it removes the need. */
  const loadedForm = useMemo(
    () =>
      loaded.data === undefined || loaded.data === null
        ? null
        : loaded.data.draft === null
          ? EMPTY_MEMO_FORM
          : memoFormFromDraft(loaded.data.draft),
    [loaded.data],
  );
  const savedForm = saved ?? (loaded.data?.draft == null ? null : loadedForm);
  const currentForm = form ?? loadedForm ?? EMPTY_MEMO_FORM;

  const evidence = evidenceEdits ?? loaded.data?.references ?? NO_EVIDENCE;
  const timepoints = loaded.data?.definitions ?? NO_TIMEPOINTS;

  /** What the hook currently holds, for the callbacks that read it.
   *
   * One ref replaced wholesale rather than three mutated field by field: the
   * value handed to `useRef` is never modified in place, which is what
   * `react(immutability)` asks for, and a single assignment cannot leave two of
   * the three momentarily disagreeing.
   *
   * It exists so `save`, `saveEvidence` and `removeEvidence` keep stable
   * identities. A callback that changed whenever the draft did would re-run the
   * publish panel's readiness effect on every keystroke. */

  useEffect(() => {
    latestRef.current = { loadedForm, evidence, form: currentForm };
  });

  /** Every published version: those the load returned, plus any published in
   * this session. Publishing appends rather than re-reading, so the history
   * grows without a second request and without overwriting anything. */
  const versions = useMemo(() => {
    const fromLoad = loaded.data?.published ?? NO_VERSIONS;
    if (publishedHere.length === 0) {
      return fromLoad;
    }
    const known = new Set(fromLoad.map((entry) => entry.version_id));
    return [...fromLoad, ...publishedHere.filter((entry) => !known.has(entry.version_id))];
  }, [loaded.data, publishedHere]);

  const retryLoad = loaded.reload;

  const isDirty = useMemo(
    () => (form === null ? false : isMemoFormDirty(form, savedForm)),
    [form, savedForm],
  );
  const hasSavedDraft = savedForm !== null;

  const save = useCallback(async (): Promise<boolean> => {
    setSaveStatus('saving');
    setSaveError(null);
    setSaveIssues([]);
    try {
      const result = await saveInvestmentMemo(
        investmentId,
        memoRequestFromForm(latest().form),
      );
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
  }, [investmentId]);

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
        setEvidenceEdits((current) => {
          const base = current ?? latest().evidence;
          const without = base.filter((item) => item.evidence_id !== result.evidence_id);
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
        setEvidenceEdits((current) =>
          (current ?? latest().evidence).filter(
            (item) => item.evidence_id !== evidenceId,
          ),
        );
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
  const strategyId = currentForm.selectedDecision?.strategy_id ?? null;
  const scenarioId = currentForm.selectedDecision?.scenario_id ?? null;

  /** The valuation surface of the selected cell.
   *
   * Keyed on the cell and the definitions the Investment holds, so choosing a
   * different Strategy or Scenario re-resolves and nothing else does. A draft
   * with no selected cell has a `null` key: there is nothing to resolve, which
   * is a real state rather than a failure. */
  const surfaceKey =
    isActive && status === 'ready' && strategyId !== null && scenarioId !== null
      ? `${investmentId}|${strategyId}|${scenarioId}|${timepoints.length}`
      : null;
  const loadSurface = useCallback(
    () => readValuationViews(investmentId, strategyId ?? '', scenarioId ?? ''),
    [investmentId, strategyId, scenarioId],
  );
  const surfaceResource = useAsyncResource(
    surfaceKey,
    loadSurface,
    'The valuation views could not be resolved.',
  );
  const surface = surfaceResource.data;
  const surfaceError = surfaceResource.error;
  const isSurfaceLoading = surfaceResource.isLoading;

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
      setPublishedHere((current) => [...current, version]);
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
    loadError: loaded.error,
    retryLoad,
    form: currentForm,
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
  /** Four reads that are only useful together: a Strategy list without its
   * Scenario list cannot populate the decision selector. Each falls back to an
   * empty list on its own failure, so one missing perspective does not blank
   * the others -- the selector then says that perspective has nothing to
   * choose, which is true. */
  const load = useCallback(async () => {
    const [strategies, scenarios, positions, partners] = await Promise.all([
      listInvestmentStrategies(investmentId).catch(() => []),
      listInvestmentScenarios(investmentId).catch(() => []),
      listPositionPerspectives(investmentId).catch(() => null),
      listPartnerPerspectives(investmentId).catch(() => null),
    ]);
    return {
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
      // The common-equity marker is a residual, not an addressable position,
      // so it is not offered as a decision perspective.
      positions: (positions?.positions ?? [])
        .filter((position) => !position.is_common_equity_marker)
        .map((position) => ({ id: position.position_id, name: position.name })),
      partners: (partners?.partners ?? []).map((partner) => ({
        id: partner.partner_id,
        name: partner.name,
      })),
    };
  }, [investmentId]);

  const resource = useAsyncResource(
    isActive ? `${investmentId}|decision-context` : null,
    load,
    'The decision context could not be loaded.',
  );

  return {
    strategies: resource.data?.strategies ?? NO_OPTIONS,
    scenarios: resource.data?.scenarios ?? NO_OPTIONS,
    positions: resource.data?.positions ?? NO_OPTIONS,
    partners: resource.data?.partners ?? NO_OPTIONS,
    isLoading: resource.isLoading,
    error: resource.error,
  };
}
