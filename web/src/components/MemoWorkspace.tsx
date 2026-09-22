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

import { useCallback, useEffect, useState } from 'react';
import { readMemoReportPreview, readMemoVersionReport } from '../api';
import { memoId } from '../memoCatalog';
import type { MemoReportPackage } from '../memoTypes';
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
  const [preview, setPreview] = useState<MemoReportPackage | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);
  const [openVersionId, setOpenVersionId] = useState<string | null>(initialVersionId);
  const [versionReport, setVersionReport] = useState<MemoReportPackage | null>(null);
  const [versionError, setVersionError] = useState<string | null>(null);

  useEffect(() => {
    onUnsavedChange?.(
      memo.isDirty ? 'This memo has unsaved changes. Leaving now discards them.' : null,
    );
  }, [memo.isDirty, onUnsavedChange]);

  const loadVersionDetail = useCallback(
    (versionId: string) => {
      void memo.loadFreshness(versionId);
      void memo.loadDecision(versionId);
    },
    [memo],
  );

  /** The preview follows the *saved* draft, so what it shows is what would be
   * published. A dirty draft says so rather than previewing edits the backend
   * has not seen. */
  const loadPreview = useCallback(async () => {
    setIsPreviewLoading(true);
    setPreviewError(null);
    try {
      setPreview(await readMemoReportPreview(investmentId));
    } catch (error) {
      setPreview(null);
      setPreviewError(
        error instanceof Error && error.message !== ''
          ? error.message
          : 'The report preview could not be built.',
      );
    } finally {
      setIsPreviewLoading(false);
    }
  }, [investmentId]);

  useEffect(() => {
    if (tab === 'publish' && memo.hasSavedDraft && isShown) {
      void loadPreview();
    }
  }, [tab, memo.hasSavedDraft, isShown, loadPreview]);

  useEffect(() => {
    if (openVersionId === null) {
      setVersionReport(null);
      return;
    }
    let cancelled = false;
    setVersionError(null);
    void readMemoVersionReport(investmentId, openVersionId)
      .then((report) => {
        if (!cancelled) {
          setVersionReport(report);
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setVersionReport(null);
          setVersionError(
            error instanceof Error && error.message !== ''
              ? error.message
              : 'The published version could not be opened.',
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [investmentId, openVersionId]);

  const citations = buildCitations(memo.form);

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
                        await loadPreview();
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
                  onRefreshReadiness={memo.refreshReadiness}
                  onPublish={memo.publish}
                  isPublishing={memo.isPublishing}
                  publishRefusals={[]}
                  publishError={null}
                  versions={memo.versions}
                  freshness={memo.freshness}
                  decisions={memo.decisions}
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
