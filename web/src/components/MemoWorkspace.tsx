/**
 * Phase 7 Gate P7.10 Stage 4 -- the Investment Committee memo workspace.
 *
 * A first-class workspace, not a modal: the memo is the analyst's decision
 * workflow and has to survive navigation, keep drafts, and be deep-linkable to
 * a published version.
 *
 * Six tabs, the smallest structure that keeps the workflow legible: Decision
 * Summary, Valuation, Thesis & Risk, Evidence, Preview & Publish, and Published
 * Versions. Each panel is its own `tabpanel`; panels stay mounted and hidden so
 * an open draft, an expanded source picker and a half-typed risk all survive a
 * tab change.
 *
 * **What is mutable and what is not is never ambiguous.** The draft header says
 * so and carries the save state; a published version opens in a clearly marked
 * read-only view with a route back to the draft, and there is no control
 * anywhere that would edit one.
 *
 * **Stage 4 ships no AI.** There is no AI tab, no AI panel, no disabled AI
 * button and no "coming soon" surface. Stage 3 is deferred and unstarted, and a
 * later authorized Stage 3 can add proposals to the draft without changing this
 * workspace's authority.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { readMemoReportPreview, readMemoVersionReport } from '../api';
import { DEPENDENCY_LABELS, memoId, STALE_VERSION_HINT } from '../memoCatalog';
import { useAsyncResource } from '../useAsyncResource';
import { useInvestmentMemo, useMemoDecisionContext } from '../useInvestmentMemo';
import { MemoDecisionPanel } from './MemoDecisionPanel';
import { MemoEvidencePanel } from './MemoEvidencePanel';
import { MemoNarrativePanel } from './MemoNarrativePanel';
import { MemoPublishPanel } from './MemoPublishPanel';
import { MemoReportView } from './MemoReportView';
import { MemoValuationPanel } from './MemoValuationPanel';

export interface MemoWorkspaceProps {
  investmentId: string;
  /** What the analyst calls this thing. A standalone Deal's memo keeps saying
   * "Deal" throughout, because its hidden one-unit Investment is an
   * implementation detail they never asked for. */
  name: string;
  /** `true` when this memo belongs to a standalone Deal. */
  isDeal: boolean;
  onClose: () => void;
  onUnsavedChange?: (warning: string | null) => void;
  isShown?: boolean;
  /** A version to open on arrival, for a deep link into a published memo. */
  initialVersionId?: string | null;
}

type MemoTabId = 'decision' | 'valuation' | 'narrative' | 'evidence' | 'publish' | 'versions';

const MEMO_TABS: { id: MemoTabId; label: string; subtitle: string }[] = [
  {
    id: 'decision',
    label: 'Decision Summary',
    subtitle: 'The ask, your recommendation, and the decision this memo is written from.',
  },
  {
    id: 'valuation',
    label: 'Valuation',
    subtitle: 'The valuation views this memo includes, and what each is worth.',
  },
  {
    id: 'narrative',
    label: 'Thesis & Risk',
    subtitle: 'Thesis, business plan, risks and mitigants, conditions and terms.',
  },
  {
    id: 'evidence',
    label: 'Evidence',
    subtitle: 'The sources this package rests on, and which claim each supports.',
  },
  {
    id: 'publish',
    label: 'Preview & Publish',
    subtitle: 'The draft report, the publication checks, and publishing a version.',
  },
  {
    id: 'versions',
    label: 'Published Versions',
    subtitle: 'The permanent record, its freshness, and the committee decision.',
  },
];

export function MemoWorkspace({
  investmentId,
  name,
  isDeal,
  onClose,
  onUnsavedChange,
  isShown = true,
  initialVersionId = null,
}: MemoWorkspaceProps) {
  const memo = useInvestmentMemo({ investmentId, isActive: isShown });
  const context = useMemoDecisionContext(investmentId, isShown);
  const [tab, setTab] = useState<MemoTabId>('decision');
  const [previewToken, setPreviewToken] = useState(0);
  const [openVersionId, setOpenVersionId] = useState<string | null>(initialVersionId);

  useEffect(() => {
    onUnsavedChange?.(
      memo.isDirty ? 'This memo has unsaved changes. Leaving now discards them.' : null,
    );
  }, [memo.isDirty, onUnsavedChange]);

  /** Reads one version's freshness and committee decision.
   *
   * Depends on the two hook functions rather than on `memo`, which is a fresh
   * object every render: a callback that changed every render would make the
   * effect below re-fire every render, and each pass would set state and cause
   * the next. Browser QA caught exactly that -- an unbounded request loop that
   * ran the tab out of sockets. `loadFreshness` and `loadDecision` are
   * `useCallback`s keyed on the Investment, so this identity is stable. */
  const { loadFreshness, loadDecision, loadReportAvailability } = memo;
  const loadVersionDetail = useCallback(
    (versionId: string) => {
      void loadFreshness(versionId);
      void loadDecision(versionId);
      // Whether the version has an issued report at all, so the list offers a
      // download only where one exists (Correction 1's pre-v16 versions).
      void loadReportAvailability(versionId);
    },
    [loadFreshness, loadDecision, loadReportAvailability],
  );

  /**
   * The registers a refusal's scope is named from.
   *
   * **Correction 2 of the second Stage 4 review.** Every one of these lists is
   * already loaded here for the analyst's own use, so naming a scope costs
   * nothing and needs no second source of truth: the valuation views are the
   * ones this Investment defines, the perspectives are the ones the decision
   * selector offers, the sources are the memo's own register, and the items are
   * the claims the analyst wrote. A scope that resolves to none of them is
   * reported as no longer available rather than as its id.
   */
  const scopes = useMemo(
    () => ({
      timepoints: memo.timepoints.map((definition) => ({
        id: definition.timepoint_id,
        label: definition.label,
      })),
      strategies: context.strategies.map((entry) => ({ id: entry.id, label: entry.name })),
      scenarios: context.scenarios.map((entry) => ({ id: entry.id, label: entry.name })),
      perspectives: [...context.positions, ...context.partners].map((entry) => ({
        id: entry.id,
        label: entry.name,
      })),
      evidence: memo.evidence.map((source) => ({ id: source.evidence_id, label: source.title })),
      items: [
        ...memo.form.items.map((item) => ({ id: item.itemId, label: item.text })),
        ...memo.form.riskItems.map((item) => ({ id: item.itemId, label: item.text })),
        ...memo.form.termItems.map((item) => ({ id: item.itemId, label: item.text })),
      ],
    }),
    [
      memo.timepoints,
      memo.evidence,
      memo.form.items,
      memo.form.riskItems,
      memo.form.termItems,
      context.strategies,
      context.scenarios,
      context.positions,
      context.partners,
    ],
  );

  /** The open version's freshness, read as soon as it is opened, so the
   * workspace can say beside the frozen report whether the analysis has moved.
   * Declared after `loadVersionDetail`, which it calls. */
  useEffect(() => {
    if (openVersionId !== null) {
      loadVersionDetail(openVersionId);
    }
  }, [openVersionId, loadVersionDetail]);

  /** The preview follows the *saved* draft, so what it shows is what would be
   * published. A dirty draft says so rather than previewing edits the backend
   * has not seen.
   *
   * Keyed on the tab being open and on `previewToken`, which publishing bumps:
   * the preview is only read while it is on screen, and is re-read after a
   * publication because the draft's relationship to the history has changed. */
  const previewKey =
    tab === 'publish' && memo.hasSavedDraft && isShown
      ? `${investmentId}|preview|${previewToken}`
      : null;
  const loadPreview = useCallback(() => readMemoReportPreview(investmentId), [investmentId]);
  const previewResource = useAsyncResource(
    previewKey,
    loadPreview,
    'The report preview could not be built.',
  );
  const preview = previewResource.data;
  const previewError = previewResource.error;
  const isPreviewLoading = previewResource.isLoading;

  /** The open published version's frozen report.
   *
   * Read, never recomputed: the backend returns the artifact stored when that
   * version was published, so this does not move when the analysis does. A
   * version published before Anchor stored reports answers with a typed
   * `unavailable` rather than an error, and the view says so. */
  const loadVersionReport = useCallback(
    () => readMemoVersionReport(investmentId, openVersionId ?? ''),
    [investmentId, openVersionId],
  );
  const versionResource = useAsyncResource(
    openVersionId === null ? null : `${investmentId}|${openVersionId}`,
    loadVersionReport,
    'The published version could not be opened.',
  );
  const versionReport = versionResource.data?.report ?? null;
  const versionUnavailable = versionResource.data?.unavailable ?? null;
  const versionError = versionResource.error;

  const citations = buildCitations(memo.form);
  const openFreshness = openVersionId === null ? undefined : memo.freshness[openVersionId];

  if (memo.status === 'loading') {
    return (
      <div className="workspace-scroll">
        <p className="scenario-muted" role="status">
          Loading memo…
        </p>
      </div>
    );
  }

  if (memo.status === 'error') {
    return (
      <div className="workspace-scroll">
        <div className="error-banner" role="alert">
          <span>{memo.loadError}</span>
          <button type="button" className="btn btn-ghost btn-xs" onClick={memo.retryLoad}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  // A published version replaces the authoring surface while it is open, so no
  // editing control is ever on screen beside an immutable record.
  if (openVersionId !== null) {
    return (
      <>
        <header className="deal-header memo-header">
          <div className="deal-header-row">
            <div className="memo-header-identity">
              <h1 className="memo-header-name">{name}</h1>
              <span className="memo-kind-tag">Published memo</span>
            </div>
            <div className="deal-header-actions">
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setOpenVersionId(null)}
              >
                Back to draft
              </button>
            </div>
          </div>
        </header>
        <div className="workspace-scroll">
          {versionError !== null && (
            <div className="error-banner" role="alert">
              <span>{versionError}</span>
            </div>
          )}

          {/* Current freshness is reported *around* the frozen document, never
            * inside it. The report below is what the committee was issued; this
            * says whether the analysis has moved since, which is a different
            * fact and belongs in the workspace. */}
          {openFreshness !== undefined && openFreshness.freshness === 'stale' && (
            <div className="memo-report-stale" role="status">
              <p className="memo-report-stale-title">
                <span className="memo-report-status">Analysis has changed</span>
              </p>
              <p className="memo-report-stale-detail">{STALE_VERSION_HINT}</p>
              {openFreshness.stale_classes.length > 0 && (
                <p className="memo-report-stale-classes">
                  Changed since publication:{' '}
                  {openFreshness.stale_classes
                    .map((entry) => DEPENDENCY_LABELS[entry] ?? entry)
                    .join(', ')}
                </p>
              )}
            </div>
          )}

          {versionUnavailable !== null && (
            <div className="memo-disclosure" role="note">
              <p className="memo-disclosure-title">No issued report for this version</p>
              <p className="memo-disclosure-detail">{versionUnavailable.message}</p>
            </div>
          )}

          {versionReport !== null && <MemoReportView report={versionReport} />}
        </div>
      </>
    );
  }

  return (
    <>
      <header className="deal-header memo-header">
        <div className="deal-header-row">
          <div className="memo-header-identity">
            <h1 className="memo-header-name">{name}</h1>
            <span className="memo-kind-tag">{isDeal ? 'Deal memo' : 'Investment memo'}</span>
            <span className="memo-header-state">Draft</span>
          </div>
          <div className="deal-header-actions">
            {memo.isDirty && (
              <span className="save-status save-status-unsaved-changes">
                <span className="save-status-dot" aria-hidden="true" />
                Unsaved changes
              </span>
            )}
            {memo.saveStatus === 'saved' && !memo.isDirty && (
              <span className="save-status" role="status">
                Saved
              </span>
            )}
            <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
              Close memo
            </button>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => void memo.save()}
              disabled={memo.saveStatus === 'saving' || !memo.isDirty}
            >
              {memo.saveStatus === 'saving' ? 'Saving…' : 'Save draft'}
            </button>
          </div>
        </div>
        {memo.saveError !== null && (
          <div className="error-banner" role="alert">
            <span>{memo.saveError}</span>
          </div>
        )}
      </header>

      <div className="workspace-nav" role="tablist" aria-label="Investment memo">
        {MEMO_TABS.map((entry) => (
          <button
            key={entry.id}
            id={memoId(`tab-${entry.id}`)}
            type="button"
            role="tab"
            aria-selected={tab === entry.id}
            aria-controls={memoId(`panel-${entry.id}`)}
            className={tab === entry.id ? 'workspace-tab workspace-tab-active' : 'workspace-tab'}
            onClick={() => setTab(entry.id)}
          >
            {entry.label}
          </button>
        ))}
      </div>

      <div className="workspace-scroll">
        {MEMO_TABS.map((entry) => (
          <section
            key={entry.id}
            id={memoId(`panel-${entry.id}`)}
            role="tabpanel"
            aria-labelledby={memoId(`tab-${entry.id}`)}
            hidden={tab !== entry.id}
            className="workspace-panel"
          >
            <div className="workspace-panel-head">
              <h2 className="workspace-title">{entry.label}</h2>
              <p className="workspace-subtitle">{entry.subtitle}</p>
            </div>
            <div className="workspace-body">
              {entry.id === 'decision' && (
                <MemoDecisionPanel
                  form={memo.form}
                  onChange={memo.setForm}
                  context={context}
                  issues={memo.saveIssues}
                />
              )}

              {entry.id === 'valuation' && (
                <MemoValuationPanel
                  form={memo.form}
                  onChange={memo.setForm}
                  surface={memo.surface}
                  isLoading={memo.isSurfaceLoading}
                  error={memo.surfaceError}
                  hasSelectedCell={memo.form.selectedDecision !== null}
                  scopes={scopes}
                />
              )}

              {entry.id === 'narrative' && (
                <MemoNarrativePanel
                  form={memo.form}
                  onChange={memo.setForm}
                  evidence={memo.evidence}
                />
              )}

              {entry.id === 'evidence' && (
                <MemoEvidencePanel
                  investmentId={investmentId}
                  evidence={memo.evidence}
                  onSave={memo.saveEvidence}
                  onRemove={memo.removeEvidence}
                  error={memo.evidenceError}
                  inUse={memo.evidenceInUse}
                  onClearError={memo.clearEvidenceError}
                  citations={citations}
                />
              )}

              {entry.id === 'publish' && (
                <div className="memo-publish-layout">
                  <MemoPublishPanel
                    investmentId={investmentId}
                    isDirty={memo.isDirty}
                    hasSavedDraft={memo.hasSavedDraft}
                    readiness={memo.readiness}
                    isReadinessLoading={memo.isReadinessLoading}
                    onRefreshReadiness={memo.refreshReadiness}
                    onPublish={async () => {
                      const version = await memo.publish();
                      if (version !== null) {
                        setPreviewToken((count) => count + 1);
                        setOpenVersionId(version.version_id);
                      }
                      return version;
                    }}
                    isPublishing={memo.isPublishing}
                    publishRefusals={memo.publishRefusals}
                    publishError={memo.publishError}
                    versions={memo.versions}
                    freshness={memo.freshness}
                    decisions={memo.decisions}
                    scopes={scopes}
                    reportAvailability={memo.reportAvailability}
                    onLoadVersionDetail={loadVersionDetail}
                    onRecordDecision={memo.recordDecision}
                    decisionError={memo.decisionError}
                    isRecordingDecision={memo.isRecordingDecision}
                    onOpenVersion={setOpenVersionId}
                    show="publish"
                  />

                  <section className="memo-section">
                    <h3 className="memo-section-title">Report preview</h3>
                    {memo.isDirty && (
                      <p className="memo-empty" role="status">
                        This preview shows the last saved draft. Save to see your latest edits.
                      </p>
                    )}
                    {isPreviewLoading && (
                      <p className="memo-empty" role="status">
                        Building the preview…
                      </p>
                    )}
                    {previewError !== null && (
                      <div className="error-banner" role="alert">
                        <span>{previewError}</span>
                      </div>
                    )}
                    {preview !== null && <MemoReportView report={preview} />}
                  </section>
                </div>
              )}

              {entry.id === 'versions' && (
                <MemoPublishPanel
                  investmentId={investmentId}
                  isDirty={memo.isDirty}
                  hasSavedDraft={memo.hasSavedDraft}
                  readiness={memo.readiness}
                  isReadinessLoading={memo.isReadinessLoading}
                  scopes={scopes}
                  onRefreshReadiness={memo.refreshReadiness}
                  onPublish={memo.publish}
                  isPublishing={memo.isPublishing}
                  publishRefusals={[]}
                  publishError={null}
                  versions={memo.versions}
                  freshness={memo.freshness}
                  decisions={memo.decisions}
                  reportAvailability={memo.reportAvailability}
                  onLoadVersionDetail={loadVersionDetail}
                  onRecordDecision={memo.recordDecision}
                  decisionError={memo.decisionError}
                  isRecordingDecision={memo.isRecordingDecision}
                  onOpenVersion={setOpenVersionId}
                  show="versions"
                />
              )}
            </div>
          </section>
        ))}
      </div>
    </>
  );
}

/**
 * Which claims cite each source, by evidence id.
 *
 * The reverse of the per-claim links, built from the draft the analyst is
 * editing so the source register can say what rests on a row before they try to
 * remove it. It reads the claim's own text; it derives nothing.
 */
function buildCitations(form: {
  items: { text: string; evidenceIds: string[] }[];
  riskItems: { text: string; evidenceIds: string[] }[];
  termItems: { text: string; evidenceIds: string[] }[];
}): Record<string, string[]> {
  const citations: Record<string, string[]> = {};
  const all = [...form.items, ...form.riskItems, ...form.termItems];
  for (const claim of all) {
    for (const evidenceId of claim.evidenceIds) {
      const label = claim.text === '' ? 'Untitled claim' : claim.text;
      citations[evidenceId] = [...(citations[evidenceId] ?? []), label];
    }
  }
  return citations;
}
