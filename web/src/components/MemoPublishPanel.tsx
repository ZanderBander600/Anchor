/**
 * Phase 7 Gate P7.10 Stage 4 -- publication readiness, publishing, and the
 * published record.
 *
 * **Readiness is the backend's answer, grouped, never re-derived.** Every reason
 * comes from the accepted Stage 2 refusal contract. This panel groups them by
 * the action that fixes each and prints the backend's own message and affected
 * scope beneath -- grouping adds a heading and never replaces a reason, so
 * nothing is reduced to a generic red banner.
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
  PUBLISHED_IMMUTABLE_HINT,
  RECOMMENDATION_LABELS,
  REFUSAL_GROUP_LABELS,
  REFUSAL_GROUP_ORDER,
  refusalGroupOf,
} from '../memoCatalog';

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
  onLoadVersionDetail: (versionId: string) => void;
  onRecordDecision: (
    versionId: string,
    decision: InvestmentCommitteeOutcome,
    note: string,
  ) => Promise<boolean>;
  decisionError: string | null;
  isRecordingDecision: boolean;
  onOpenVersion: (versionId: string) => void;
}

function RefusalGroups({ refusals }: { refusals: PublicationRefusal[] }) {
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
                <li key={`${refusal.code}-${refusal.scope_id ?? ''}-${refusal.message}`}>
                  {/* The backend's own sentence, never paraphrased. */}
                  <p className="memo-refusal-message">{refusal.message}</p>
                  {refusal.scope_id !== null && (
                    <p className="memo-refusal-scope">Affects: {refusal.scope_id}</p>
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
    onLoadVersionDetail,
    onRecordDecision,
    decisionError,
    isRecordingDecision,
    onOpenVersion,
  } = props;

  const [isConfirming, setIsConfirming] = useState(false);
  const refusalRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!hasSavedDraft) {
      return;
    }
    void onRefreshReadiness();
  }, [hasSavedDraft, onRefreshReadiness]);

  useEffect(() => {
    for (const version of versions) {
      onLoadVersionDetail(version.version_id);
    }
  }, [versions, onLoadVersionDetail]);

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
            <RefusalGroups refusals={refusals} />
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
                        Published {version.created_at}
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
                        * equivalent, and no route that would accept one. */}
                      <a
                        className="btn btn-ghost btn-xs"
                        href={memoPdfUrl(investmentId, version.version_id)}
                        download
                      >
                        Download PDF
                      </a>
                    </div>
                  </div>

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
