/**
 * Phase 7 Gate P7.10 Stage 4 -- the draft's source register.
 *
 * Where sources are created, described, approved and removed. Claims attach to
 * them from wherever the claim is authored; this is the library those
 * attachments point into.
 *
 * **Three separate facts, three separate columns (Section 8).** What kind of
 * source it is, whether the analyst has approved it, and which claims rest on
 * it. Collapsing any two would be the silent upgrade the contract forbids: an
 * attached source is not an approved one, and an approved one is not a verified
 * one. Anchor verifies nothing here -- it stores a reference and never fetches,
 * reads or copies what that reference points at.
 *
 * **A source in use cannot be removed, and the refusal says what holds it.** The
 * backend refuses rather than cascading, because cascading would leave a claim,
 * or an analyst-supplied valuation, pointing at a source that no longer exists.
 * The panel shows exactly what to detach.
 *
 * **No AI touches this.** Nothing here proposes, finds, extracts or approves a
 * source. `ai_extracted_approved` is a provenance label an analyst chooses to
 * record about a source *they* approved, not a capability Stage 4 ships.
 */

import { useState } from 'react';
import { newEvidenceReference } from '../memoForm';
import type { MemoEvidenceReference } from '../memoTypes';
import type { EvidenceSourceKind } from '../memoTypes';
import {
  DELETE_EVIDENCE_IN_USE_HINT,
  EVIDENCE_KIND_LABELS,
  EVIDENCE_KIND_ORDER,
} from '../memoCatalog';
import type { EvidenceInUseError } from '../api';

export interface MemoEvidencePanelProps {
  investmentId: string;
  evidence: MemoEvidenceReference[];
  onSave: (reference: MemoEvidenceReference) => Promise<boolean>;
  onRemove: (evidenceId: string) => Promise<boolean>;
  error: string | null;
  inUse: EvidenceInUseError | null;
  onClearError: () => void;
  /** Which claims cite each source, by id, so the register can say what rests
   * on a row before the analyst tries to remove it. */
  citations: Record<string, string[]>;
}

export function MemoEvidencePanel({
  investmentId,
  evidence,
  onSave,
  onRemove,
  error,
  inUse,
  onClearError,
  citations,
}: MemoEvidencePanelProps) {
  const [draft, setDraft] = useState<MemoEvidenceReference | null>(null);
  const [pendingRemoval, setPendingRemoval] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  function startNew(): void {
    onClearError();
    setDraft(newEvidenceReference(investmentId, evidence.length));
  }

  async function commit(reference: MemoEvidenceReference): Promise<void> {
    setIsSaving(true);
    const saved = await onSave(reference);
    setIsSaving(false);
    if (saved) {
      setDraft(null);
    }
  }

  return (
    <div className="memo-panel">
      <section className="memo-section">
        <div className="memo-section-head">
          <h3 className="memo-section-title">Sources</h3>
          <button type="button" className="btn btn-secondary btn-xs" onClick={startNew}>
            Add source
          </button>
        </div>
        <p className="memo-section-hint">
          Anchor stores a reference, never a copy of the document, and does not verify it.
          Approval is your own act, and a claim may cite nothing at all.
        </p>

        {error !== null && (
          <div className="error-banner" role="alert">
            <span>{error}</span>
            <button type="button" className="btn btn-ghost btn-xs" onClick={onClearError}>
              Dismiss
            </button>
          </div>
        )}

        {inUse !== null && (
          <div className="memo-disclosure" role="note">
            <p className="memo-disclosure-title">This source is still in use</p>
            <p className="memo-disclosure-detail">{DELETE_EVIDENCE_IN_USE_HINT}</p>
            {inUse.valuationTimepointIds.length > 0 && (
              <p className="memo-disclosure-detail">
                It supports an analyst-supplied valuation, which would have no source without it.
              </p>
            )}
            {inUse.citedByDraft && (
              <p className="memo-disclosure-detail">A claim in this memo cites it.</p>
            )}
          </div>
        )}

        {draft !== null && (
          <EvidenceEditor
            reference={draft}
            isSaving={isSaving}
            onChange={setDraft}
            onCancel={() => setDraft(null)}
            onSave={() => void commit(draft)}
          />
        )}

        {evidence.length === 0 && draft === null ? (
          <p className="memo-empty">
            No sources recorded. Claims can still be authored; each will be labelled an analyst
            assertion.
          </p>
        ) : (
          <ul className="memo-item-list">
            {evidence.map((item) => {
              const cited = citations[item.evidence_id] ?? [];
              return (
                <li key={item.evidence_id} className="memo-item">
                  <div className="memo-evidence-row">
                    <div className="memo-evidence-identity">
                      <p className="memo-evidence-title">
                        {item.title === '' ? 'Untitled source' : item.title}
                      </p>
                      <p className="memo-evidence-meta">
                        {EVIDENCE_KIND_LABELS[item.source_kind]}
                        {item.as_of_date !== null && <> · As of {item.as_of_date}</>}
                      </p>
                      <p className="memo-evidence-reference">{item.reference}</p>
                      <p className="memo-evidence-cited">
                        {cited.length > 0
                          ? `Supports: ${cited.join('; ')}`
                          : 'Not cited by any claim yet.'}
                      </p>
                    </div>

                    <div className="memo-evidence-controls">
                      {/* Approval is words, not colour: the state survives a
                        * monochrome display and a screen reader. */}
                      <label className="memo-approve">
                        <input
                          type="checkbox"
                          checked={item.approved}
                          onChange={() =>
                            void onSave({ ...item, approved: !item.approved })
                          }
                        />
                        <span>{item.approved ? 'Approved' : 'Not approved'}</span>
                      </label>
                      <button
                        type="button"
                        className="btn btn-ghost btn-xs"
                        onClick={() => {
                          onClearError();
                          setDraft(item);
                        }}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost btn-xs"
                        onClick={() => {
                          onClearError();
                          setPendingRemoval(item.evidence_id);
                        }}
                      >
                        Remove
                      </button>
                    </div>
                  </div>

                  {pendingRemoval === item.evidence_id && (
                    <div
                      className="memo-remove-confirm"
                      role="group"
                      aria-label={`Confirm removing ${item.title}`}
                    >
                      <p className="memo-remove-text">
                        Remove this source? A claim that still cites it will refuse.
                      </p>
                      <div className="memo-remove-actions">
                        <button
                          type="button"
                          className="btn btn-danger btn-xs"
                          onClick={() => {
                            setPendingRemoval(null);
                            void onRemove(item.evidence_id);
                          }}
                        >
                          Remove
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost btn-xs"
                          onClick={() => setPendingRemoval(null)}
                          autoFocus
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}

function EvidenceEditor({
  reference,
  isSaving,
  onChange,
  onCancel,
  onSave,
}: {
  reference: MemoEvidenceReference;
  isSaving: boolean;
  onChange: (next: MemoEvidenceReference) => void;
  onCancel: () => void;
  onSave: () => void;
}) {
  return (
    <div className="memo-evidence-editor" role="group" aria-label="Source details">
      <div className="memo-field-grid">
        <label className="memo-field">
          <span className="memo-field-label">Title</span>
          <input
            className="memo-input"
            type="text"
            value={reference.title}
            onChange={(event) => onChange({ ...reference, title: event.target.value })}
            autoFocus
          />
        </label>

        <label className="memo-field">
          <span className="memo-field-label">Kind</span>
          <select
            className="memo-select"
            value={reference.source_kind}
            onChange={(event) =>
              onChange({ ...reference, source_kind: event.target.value as EvidenceSourceKind })
            }
          >
            {EVIDENCE_KIND_ORDER.map((value) => (
              <option key={value} value={value}>
                {EVIDENCE_KIND_LABELS[value]}
              </option>
            ))}
          </select>
        </label>

        <label className="memo-field">
          <span className="memo-field-label">As of</span>
          <input
            className="memo-input"
            type="date"
            value={reference.as_of_date ?? ''}
            onChange={(event) =>
              onChange({
                ...reference,
                as_of_date: event.target.value === '' ? null : event.target.value,
              })
            }
          />
        </label>
      </div>

      <label className="memo-field">
        <span className="memo-field-label">Reference</span>
        <input
          className="memo-input"
          type="text"
          value={reference.reference}
          onChange={(event) => onChange({ ...reference, reference: event.target.value })}
          placeholder="Document anchor, URL, or analyst note"
        />
      </label>

      <label className="memo-approve">
        <input
          type="checkbox"
          checked={reference.approved}
          onChange={(event) => onChange({ ...reference, approved: event.target.checked })}
        />
        <span>Approved — this source may support a published claim</span>
      </label>

      <div className="memo-editor-actions">
        <button type="button" className="btn btn-primary btn-sm" onClick={onSave} disabled={isSaving}>
          {isSaving ? 'Saving…' : 'Save source'}
        </button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel} disabled={isSaving}>
          Cancel
        </button>
      </div>
    </div>
  );
}
