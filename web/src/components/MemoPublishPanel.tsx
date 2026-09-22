/**
 * Phase 7 Gate P7.10 Stage 4 -- publication readiness, publishing, and the
 * published record.
 *
 * **Readiness is the backend's answer, grouped, never re-derived.** Every reason
 * comes from the accepted Stage 2 refusal contract. This panel groups them by
 * the action that fixes each and prints each refusal beneath -- grouping adds a
 * heading and never replaces a reason, so nothing is reduced to a generic red
 * banner.
 *
 * Each refusal is **translated from its stable code**, exactly as an unavailable
 * valuation is. Browser QA at the independent review found the alternative on
 * screen: the backend's own sentence names the Investment, the timepoint and the
 * Unit by their opaque ids, in the one place the analyst is being asked to go
 * and fix something. The upstream reason a refusal carries is appended, so the
 * specific cause survives the translation.
 *
 * **Publishing is explicit and confirmed.** It takes a deliberate second act, it
 * creates a new immutable version, and it never overwrites an earlier one. A
 * refusal keeps the analyst here, in context, with the first actionable issue
 * focused.
 *
 * **A published version cannot be edited.** There is no control here that would
 * try. The route back to the draft is stated plainly instead, because "continue
 * in the draft and publish again" is the only way a memo changes.
 *
 * **The committee decision is a different act (R-F).** It is recorded against a
 * published version, after publication, in its own section with its own
 * vocabulary. It is never inferred from the analyst's recommendation, and
 * nothing here suggests one.
 */

import { useEffect, useRef, useState } from 'react';
import { memoPdfUrl } from '../api';
import type {
  InvestmentCommitteeDecision,
  InvestmentCommitteeOutcome,
  InvestmentMemoVersion,
  MemoFreshnessReport,
  PublicationRefusal,
} from '../memoTypes';
import {
  COMMITTEE_DECISION_LABEL,
  COMMITTEE_DECISION_UNRECORDED,
  COMMITTEE_LABELS,
  COMMITTEE_ORDER,
  DEPENDENCY_LABELS,
  displayDate,
  PUBLISHED_IMMUTABLE_HINT,
  RECOMMENDATION_LABELS,
  REFUSAL_GROUP_LABELS,
  REFUSAL_GROUP_ORDER,
  publicationRefusalLabel,
  publicationScopeLabel,
  refusalGroupOf,
} from '../memoCatalog';
import type { MemoScopeSources } from '../memoCatalog';

export interface MemoPublishPanelProps {
  investmentId: string;
  isDirty: boolean;
  hasSavedDraft: boolean;
  readiness: { publishable: boolean; refusals: PublicationRefusal[] } | null;
  isReadinessLoading: boolean;
  onRefreshReadiness: () => Promise<void>;
  onPublish: () => Promise<InvestmentMemoVersion | null>;
  isPublishing: boolean;
  publishRefusals: PublicationRefusal[];
  publishError: string | null;
  versions: InvestmentMemoVersion[];
  freshness: Record<string, MemoFreshnessReport>;
  decisions: Record<string, InvestmentCommitteeDecision | null>;
  /** The registers a refusal's scope is named from: the workspace's own loaded
   * valuation views, Strategies, Scenarios, perspectives, sources and memo
   * items. Presentation reads them; it never prints a stored id (Correction 2
   * of the second Stage 4 review). */
  scopes: MemoScopeSources;
  /** Whether each version has an issued report. A version published before
   * Anchor stored one has no PDF to offer, and is told so in place of a link
   * that could only refuse (found by browser QA at the independent review). */
  reportAvailability: Record<string, { issued: boolean; message: string | null }>;
  onLoadVersionDetail: (versionId: string) => void;
  onRecordDecision: (
    versionId: string,
    decision: InvestmentCommitteeOutcome,
    note: string,
  ) => Promise<boolean>;
  decisionError: string | null;
  isRecordingDecision: boolean;
  onOpenVersion: (versionId: string) => void;
  /** Which half of this panel to render.
   *
   * Preview & Publish shows the readiness checks and the publish action;
   * Published Versions shows the permanent record and the committee decision.
   * One component, because the two halves share state and must agree, but
   * never both halves at once -- two tabs rendering the same section would put
   * two copies of every heading and control in the accessibility tree, and an
   * analyst tabbing through would meet each twice. */
  show: 'publish' | 'versions';
}

function RefusalGroups({
  refusals,
  scopes,
}: {
  refusals: PublicationRefusal[];
  scopes: MemoScopeSources;
}) {
  const grouped = new Map<string, PublicationRefusal[]>();
  for (const refusal of refusals) {
    const group = refusalGroupOf(refusal.code);
    grouped.set(group, [...(grouped.get(group) ?? []), refusal]);
  }

  return (
    <div className="memo-refusals">
      {REFUSAL_GROUP_ORDER.filter((group) => grouped.has(group)).map((group) => {
        const meta = REFUSAL_GROUP_LABELS[group];
        return (
          <section key={group} className="memo-refusal-group">
            <h4 className="memo-refusal-title">{meta.title}</h4>
            <p className="memo-refusal-action">{meta.action}</p>
            <ul className="memo-refusal-list">
              {(grouped.get(group) ?? []).map((refusal) => (
                <li key={`${refusal.code}-${refusal.scope_id ?? ''}-${refusal.field ?? ''}`}>
                  {/* Translated from the stable code, not the backend's own
                    * sentence, which names records by their opaque ids. The
                    * refusal's own upstream reason is appended by the catalog,
                    * so nothing specific is lost. */}
                  <p className="memo-refusal-message">
                    {publicationRefusalLabel(refusal.code, refusal.unavailable_reason)}
                  </p>
                  {/* Named from the register the refusal's own code points at,
                    * never printed as the stored id. */}
                  {publicationScopeLabel(refusal.code, refusal.scope_id, scopes) !== null && (
                    <p className="memo-refusal-scope">
                      Affects: {publicationScopeLabel(refusal.code, refusal.scope_id, scopes)}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

export function MemoPublishPanel(props: MemoPublishPanelProps) {
  const {
    investmentId,
    isDirty,
    hasSavedDraft,
    readiness,
    isReadinessLoading,
    onRefreshReadiness,
    onPublish,
    isPublishing,
    publishRefusals,
    publishError,
    versions,
    freshness,
    decisions,
    scopes,
    reportAvailability,
    onLoadVersionDetail,
    onRecordDecision,
    decisionError,
    isRecordingDecision,
    onOpenVersion,
    show,
  } = props;

  const [isConfirming, setIsConfirming] = useState(false);
  const refusalRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!hasSavedDraft) {
      return;
    }
    void onRefreshReadiness();
  }, [hasSavedDraft, onRefreshReadiness]);

  /** Each published version's freshness and committee decision, read once.
   *
   * Guarded on what is already held: a version whose detail has arrived is not
   * requested again. Without this the panel would re-request on every render
   * that produced a new `versions` array, and a published memo would keep the
   * backend busy for as long as the tab was open. */
  useEffect(() => {
    for (const version of versions) {
      if (version.version_id in freshness && version.version_id in decisions) {
        continue;
      }
      onLoadVersionDetail(version.version_id);
    }
  }, [versions, freshness, decisions, onLoadVersionDetail]);

  /** A refusal keeps the analyst in context and puts the first actionable issue
   * in front of them, rather than leaving them to find it. */
  useEffect(() => {
    if (publishRefusals.length > 0) {
      refusalRef.current?.focus();
    }
  }, [publishRefusals]);

  const refusals = publishRefusals.length > 0 ? publishRefusals : (readiness?.refusals ?? []);
  const canPublish = hasSavedDraft && !isDirty && readiness?.publishable === true;

  return (
    <div className="memo-panel">
      {show === 'publish' && (
      <section className="memo-section">
        <h3 className="memo-section-title">Publication readiness</h3>

        {!hasSavedDraft && (
          <p className="memo-empty">Save the draft before it can be published.</p>
        )}

        {isDirty && hasSavedDraft && (
          <p className="memo-empty" role="status">
            This memo has unsaved changes. Save them, then run the publication checks again.
          </p>
        )}

        {isReadinessLoading && (
          <p className="memo-empty" role="status">
            Running publication checks…
          </p>
        )}

        {readiness !== null && readiness.publishable && !isDirty && (
          <p className="memo-ready" role="status">
            Every prerequisite is satisfied. Publishing creates a new permanent version.
          </p>
        )}

        {refusals.length > 0 && (
          <div
            className="memo-refusal-region"
            tabIndex={-1}
            ref={refusalRef}
            role="group"
            aria-label="Reasons this memo cannot be published"
          >
            <RefusalGroups refusals={refusals} scopes={scopes} />
          </div>
        )}

        {publishError !== null && publishRefusals.length === 0 && (
          <div className="error-banner" role="alert">
            <span>{publishError}</span>
          </div>
        )}

        <div className="memo-editor-actions">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => void onRefreshReadiness()}
            disabled={!hasSavedDraft || isReadinessLoading}
          >
            Run checks again
          </button>

          {!isConfirming ? (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => setIsConfirming(true)}
              disabled={!canPublish || isPublishing}
            >
              Publish version
            </button>
          ) : (
            <div className="memo-publish-confirm" role="group" aria-label="Confirm publication">
              <p className="memo-remove-text">
                Publish this memo as a permanent version? It cannot be edited afterwards, and no
                earlier version is changed.
              </p>
              <div className="memo-remove-actions">
                <button
                  type="button"
                  className="btn btn-primary btn-xs"
                  disabled={isPublishing}
                  onClick={() => {
                    setIsConfirming(false);
                    void onPublish();
                  }}
                >
                  {isPublishing ? 'Publishing…' : 'Publish'}
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-xs"
                  onClick={() => setIsConfirming(false)}
                  autoFocus
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      </section>
      )}

      {show === 'versions' && (
      <section className="memo-section">
        <h3 className="memo-section-title">Published versions</h3>
        <p className="memo-section-hint">{PUBLISHED_IMMUTABLE_HINT}</p>

        {versions.length === 0 ? (
          <p className="memo-empty">Nothing published yet.</p>
        ) : (
          <ul className="memo-version-list">
            {[...versions].reverse().map((version) => {
              const report = freshness[version.version_id];
              const decision = decisions[version.version_id] ?? null;
              return (
                <li key={version.version_id} className="memo-version">
                  <div className="memo-version-head">
                    <div>
                      <p className="memo-version-number">Version {version.version_number}</p>
                      <p className="memo-version-meta">
                        Published {displayDate(version.created_at)}
                        {version.prepared_by !== null && <> · {version.prepared_by}</>}
                      </p>
                      <p className="memo-version-meta">
                        Analyst recommendation:{' '}
                        {RECOMMENDATION_LABELS[version.analyst_recommendation]}
                      </p>
                    </div>
                    <div className="memo-version-controls">
                      {/* Freshness is words, never colour alone. */}
                      {report !== undefined && (
                        <span
                          className={
                            report.freshness === 'current'
                              ? 'memo-tag memo-tag-approved'
                              : 'memo-tag memo-tag-open'
                          }
                        >
                          {report.freshness === 'current' ? 'Current' : 'Analysis has changed'}
                        </span>
                      )}
                      <button
                        type="button"
                        className="btn btn-secondary btn-xs"
                        onClick={() => onOpenVersion(version.version_id)}
                      >
                        Open
                      </button>
                      {/* The download is a plain link so the file lands with
                        * the name the backend chose. There is no draft
                        * equivalent, and no route that would accept one.
                        *
                        * A version published before Anchor stored a report with
                        * each publication has no PDF to download, so it is not
                        * offered one: browser QA at the independent review
                        * followed that link and landed on a raw refusal
                        * payload. The sentence beneath says what to do
                        * instead. */}
                      {reportAvailability[version.version_id]?.issued === false ? (
                        <span className="memo-version-no-report">No issued PDF</span>
                      ) : (
                        <a
                          className="btn btn-ghost btn-xs"
                          href={memoPdfUrl(investmentId, version.version_id)}
                          download
                        >
                          Download PDF
                        </a>
                      )}
                    </div>
                  </div>

                  {reportAvailability[version.version_id]?.issued === false && (
                    <p className="memo-version-no-report-detail">
                      {reportAvailability[version.version_id]?.message}
                    </p>
                  )}

                  {report !== undefined && report.stale_classes.length > 0 && (
                    <p className="memo-version-stale">
                      Changed since publication:{' '}
                      {report.stale_classes
                        .map((entry) => DEPENDENCY_LABELS[entry] ?? entry)
                        .join(', ')}
                    </p>
                  )}

                  <CommitteeDecisionEditor
                    versionId={version.version_id}
                    decision={decision}
                    onRecord={onRecordDecision}
                    isSaving={isRecordingDecision}
                    error={decisionError}
                  />
                </li>
              );
            })}
          </ul>
        )}
      </section>
      )}
    </div>
  );
}

/**
 * The committee's own decision, recorded against one published version.
 *
 * Deliberately a separate block with its own heading and its own vocabulary:
 * `Deferred` is a committee outcome and `Insufficient Information` is an
 * analyst recommendation, and no control here offers one list in place of the
 * other. Nothing pre-selects an outcome from what the analyst recommended.
 */
function CommitteeDecisionEditor({
  versionId,
  decision,
  onRecord,
  isSaving,
  error,
}: {
  versionId: string;
  decision: InvestmentCommitteeDecision | null;
  onRecord: (
    versionId: string,
    outcome: InvestmentCommitteeOutcome,
    note: string,
  ) => Promise<boolean>;
  isSaving: boolean;
  error: string | null;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [outcome, setOutcome] = useState<InvestmentCommitteeOutcome>(
    decision?.decision ?? 'pending',
  );
  const [note, setNote] = useState(decision?.decision_note ?? '');

  return (
    <div className="memo-committee">
      <div className="memo-committee-head">
        <span className="memo-committee-label">{COMMITTEE_DECISION_LABEL}</span>
        <span className="memo-committee-value">
          {decision === null ? COMMITTEE_DECISION_UNRECORDED : COMMITTEE_LABELS[decision.decision]}
        </span>
        <button
          type="button"
          className="btn btn-ghost btn-xs"
          aria-expanded={isOpen}
          onClick={() => setIsOpen((current) => !current)}
        >
          {isOpen ? 'Close' : decision === null ? 'Record decision' : 'Update decision'}
        </button>
      </div>

      {decision?.decision_note != null && !isOpen && (
        <p className="memo-committee-note">{decision.decision_note}</p>
      )}

      {isOpen && (
        <div className="memo-committee-form" role="group" aria-label="Record the committee decision">
          <label className="memo-field">
            <span className="memo-field-label">Committee outcome</span>
            <select
              className="memo-select"
              value={outcome}
              onChange={(event) =>
                setOutcome(event.target.value as InvestmentCommitteeOutcome)
              }
            >
              {COMMITTEE_ORDER.map((value) => (
                <option key={value} value={value}>
                  {COMMITTEE_LABELS[value]}
                </option>
              ))}
            </select>
          </label>

          <label className="memo-field">
            <span className="memo-field-label">Decision note</span>
            <textarea
              className="memo-textarea"
              rows={2}
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
          </label>

          {error !== null && (
            <p className="memo-field-error" role="alert">
              {error}
            </p>
          )}

          <div className="memo-editor-actions">
            <button
              type="button"
              className="btn btn-primary btn-xs"
              disabled={isSaving}
              onClick={() => {
                void onRecord(versionId, outcome, note).then((saved) => {
                  if (saved) {
                    setIsOpen(false);
                  }
                });
              }}
            >
              {isSaving ? 'Saving…' : 'Record decision'}
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-xs"
              onClick={() => setIsOpen(false)}
              disabled={isSaving}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
