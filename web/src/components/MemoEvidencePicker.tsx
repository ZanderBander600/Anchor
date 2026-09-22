/**
 * Phase 7 Gate P7.10 Stage 4 -- attaching sources to one claim (R-G).
 *
 * The one control that links an individual thesis item, risk, mitigant,
 * condition, term or milestone to zero or more Evidence References. One control
 * rather than five, so the claim-to-source relationship looks and behaves the
 * same wherever a claim is authored.
 *
 * **Attaching a source is not verification.** Anchor has verified nothing
 * because an analyst attached something. Each row therefore shows the source's
 * own approval state as separate words -- never as styling alone, and never
 * folded into the fact that it is attached.
 *
 * **Evidence is never required.** A claim that cites nothing is a real analyst
 * assertion; the summary says so in the Section 8 words rather than leaving an
 * empty space that reads as an omission.
 *
 * **Keyboard first.** The picker is a labelled group of checkboxes, so it is
 * reachable, operable and announced without a pointer, and toggling one never
 * moves focus.
 */

import { useId, useState } from 'react';
import type { MemoEvidenceReference } from '../memoTypes';
import { EVIDENCE_KIND_LABELS, UNSOURCED_CLAIM_LABEL } from '../memoCatalog';

export interface MemoEvidencePickerProps {
  /** The Investment's whole register, approved and unapproved alike. */
  evidence: MemoEvidenceReference[];
  /** The ids this claim currently cites, in authored order. */
  selectedIds: string[];
  onChange: (next: string[]) => void;
  /** Names the claim for screen readers, so several pickers on one page are
   * told apart. */
  claimLabel: string;
}

export function MemoEvidencePicker({
  evidence,
  selectedIds,
  onChange,
  claimLabel,
}: MemoEvidencePickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const groupId = useId();
  const selected = evidence.filter((item) => selectedIds.includes(item.evidence_id));

  function toggle(evidenceId: string): void {
    onChange(
      selectedIds.includes(evidenceId)
        ? selectedIds.filter((id) => id !== evidenceId)
        : [...selectedIds, evidenceId],
    );
  }

  return (
    <div className="memo-evidence-picker">
      <div className="memo-evidence-summary">
        {selected.length > 0 ? (
          <ul className="memo-evidence-chips">
            {selected.map((item) => (
              <li key={item.evidence_id}>
                <span
                  className={
                    item.approved
                      ? 'memo-tag memo-tag-approved'
                      : 'memo-tag memo-tag-open'
                  }
                >
                  {item.title === '' ? 'Untitled source' : item.title}
                  <span className="memo-chip-state">
                    {item.approved ? 'Approved' : 'Not approved'}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="memo-evidence-none">{UNSOURCED_CLAIM_LABEL}</p>
        )}

        <button
          type="button"
          className="btn btn-ghost btn-xs"
          aria-expanded={isOpen}
          aria-controls={groupId}
          onClick={() => setIsOpen((current) => !current)}
        >
          {isOpen ? 'Done' : 'Attach sources'}
        </button>
      </div>

      {isOpen && (
        <fieldset className="memo-evidence-options" id={groupId}>
          <legend className="memo-evidence-legend">Sources supporting: {claimLabel}</legend>
          {evidence.length === 0 ? (
            <p className="memo-field-hint">
              This Investment has no sources yet. Add one on the Evidence tab, then attach it here.
            </p>
          ) : (
            <ul className="memo-evidence-list">
              {evidence.map((item) => (
                <li key={item.evidence_id}>
                  <label className="memo-evidence-option">
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(item.evidence_id)}
                      onChange={() => toggle(item.evidence_id)}
                    />
                    <span className="memo-evidence-option-text">
                      <span className="memo-evidence-option-title">
                        {item.title === '' ? 'Untitled source' : item.title}
                      </span>
                      <span className="memo-evidence-option-meta">
                        {EVIDENCE_KIND_LABELS[item.source_kind]} ·{' '}
                        {item.approved ? 'Approved' : 'Not approved'}
                      </span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </fieldset>
      )}
    </div>
  );
}
