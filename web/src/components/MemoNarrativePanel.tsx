/**
 * Phase 7 Gate P7.10 Stage 4 -- authoring the analyst's own claims.
 *
 * Thesis, Business Plan milestones, structural protections, reputational
 * concerns, dealbreakers, conditions to approval, risks with their mitigants,
 * and terms. Every one is analyst-authoritative: Anchor writes none of it, and
 * Stage 4 ships no AI that could offer to.
 *
 * **Identity survives editing (Section 7.4).** An item is its id. Editing its
 * text, changing a severity, moving it, or re-pointing its sources edits that
 * item; nothing here ever mints a replacement, so a claim keeps its evidence
 * links across every edit to either side.
 *
 * **Destructive actions confirm inline.** Removing an item asks first, in place,
 * with a real focusable control -- never a native `confirm()`, which blocks the
 * page and cannot be styled, labelled or dismissed by keyboard consistently.
 * Focus returns to the row's own controls afterwards, so the keyboard position
 * is never lost.
 *
 * **Severity is a judgement, not a calculation.** A new risk is Not Assessed
 * rather than Low, and stating a mitigant never changes either label. Section
 * 7.4 is explicit that neither is derived from a return.
 */

import { useRef, useState } from 'react';
import {
  addMemoItem,
  addMemoRisk,
  addMemoTerm,
  canMove,
  moveMemoItem,
  moveMemoRisk,
  moveMemoTerm,
  removeMemoItem,
  removeMemoRisk,
  removeMemoTerm,
  updateMemoItem,
  updateMemoRisk,
  updateMemoTerm,
} from '../memoForm';
import type { MemoDraftForm, MoveDirection } from '../memoForm';
import type { MemoEvidenceReference, MemoSectionKind, RiskSeverity, TermPriority } from '../memoTypes';
import {
  PRIORITY_LABELS,
  PRIORITY_ORDER,
  SECTION_LABELS,
  SECTION_ORDER,
  SEVERITY_LABELS,
  SEVERITY_ORDER,
} from '../memoCatalog';
import { MemoEvidencePicker } from './MemoEvidencePicker';

export interface MemoNarrativePanelProps {
  form: MemoDraftForm;
  onChange: (next: MemoDraftForm) => void;
  evidence: MemoEvidenceReference[];
}

/** The inline remove confirmation.
 *
 * A group with its own label and two real buttons. Cancel takes focus on open,
 * so the destructive option is never the one a stray Enter reaches. */
function RemoveConfirm({
  label,
  onConfirm,
  onCancel,
}: {
  label: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="memo-remove-confirm" role="group" aria-label={`Confirm removing ${label}`}>
      <p className="memo-remove-text">Remove this entry? It is not recoverable from here.</p>
      <div className="memo-remove-actions">
        <button type="button" className="btn btn-danger btn-xs" onClick={onConfirm}>
          Remove
        </button>
        <button type="button" className="btn btn-ghost btn-xs" onClick={onCancel} autoFocus>
          Cancel
        </button>
      </div>
    </div>
  );
}

/** The reorder and remove controls one authored row carries. */
function RowControls({
  order,
  itemId,
  label,
  onMove,
  onRequestRemove,
  removeRef,
}: {
  order: string[];
  itemId: string;
  label: string;
  onMove: (direction: MoveDirection) => void;
  onRequestRemove: () => void;
  removeRef: React.RefObject<HTMLButtonElement | null>;
}) {
  return (
    <div className="memo-row-controls">
      <button
        type="button"
        className="btn btn-ghost btn-xs"
        onClick={() => onMove('up')}
        disabled={!canMove(order, itemId, 'up')}
        aria-label={`Move ${label} up`}
      >
        ↑
      </button>
      <button
        type="button"
        className="btn btn-ghost btn-xs"
        onClick={() => onMove('down')}
        disabled={!canMove(order, itemId, 'down')}
        aria-label={`Move ${label} down`}
      >
        ↓
      </button>
      <button
        type="button"
        className="btn btn-remove btn-xs"
        onClick={onRequestRemove}
        aria-label={`Remove ${label}`}
        ref={removeRef}
      >
        Remove
      </button>
    </div>
  );
}

export function MemoNarrativePanel({ form, onChange, evidence }: MemoNarrativePanelProps) {
  const [pendingRemoval, setPendingRemoval] = useState<string | null>(null);
  /** Where focus returns after an inline confirmation closes, so cancelling a
   * removal never drops the analyst back to the top of the page. */
  const removeRefs = useRef(new Map<string, HTMLButtonElement | null>());

  function refFor(itemId: string): React.RefObject<HTMLButtonElement | null> {
    return {
      get current() {
        return removeRefs.current.get(itemId) ?? null;
      },
      set current(node: HTMLButtonElement | null) {
        removeRefs.current.set(itemId, node);
      },
    };
  }

  function closeConfirm(itemId: string): void {
    setPendingRemoval(null);
    removeRefs.current.get(itemId)?.focus();
  }

  function renderSection(section: MemoSectionKind) {
    const items = form.items.filter((item) => item.section === section);
    const order = items.map((item) => item.itemId);
    const meta = SECTION_LABELS[section];

    return (
      <section className="memo-section" key={section}>
        <div className="memo-section-head">
          <h3 className="memo-section-title">{meta.title}</h3>
          <button
            type="button"
            className="btn btn-add btn-xs"
            onClick={() => onChange(addMemoItem(form, section))}
          >
            {`Add ${meta.item}`}
          </button>
        </div>
        <p className="memo-section-hint">{meta.hint}</p>

        {items.length === 0 ? (
          <p className="memo-empty">Nothing recorded. This section is left out of the report.</p>
        ) : (
          <ul className="memo-item-list">
            {items.map((item) => (
              <li key={item.itemId} className="memo-item">
                <div className="memo-item-head">
                  <label className="memo-field memo-field-grow">
                    <span className="memo-field-label">{meta.title}</span>
                    <textarea
                      className="memo-textarea"
                      rows={2}
                      value={item.text}
                      onChange={(event) =>
                        onChange(updateMemoItem(form, item.itemId, { text: event.target.value }))
                      }
                    />
                  </label>
                  <RowControls
                    order={order}
                    itemId={item.itemId}
                    label={meta.title}
                    onMove={(direction) => onChange(moveMemoItem(form, item.itemId, direction))}
                    onRequestRemove={() => setPendingRemoval(item.itemId)}
                    removeRef={refFor(item.itemId)}
                  />
                </div>

                <MemoEvidencePicker
                  evidence={evidence}
                  selectedIds={item.evidenceIds}
                  claimLabel={item.text === '' ? meta.title : item.text}
                  onChange={(next) =>
                    onChange(updateMemoItem(form, item.itemId, { evidenceIds: next }))
                  }
                />

                {pendingRemoval === item.itemId && (
                  <RemoveConfirm
                    label={meta.title}
                    onConfirm={() => {
                      setPendingRemoval(null);
                      onChange(removeMemoItem(form, item.itemId));
                    }}
                    onCancel={() => closeConfirm(item.itemId)}
                  />
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    );
  }

  const riskOrder = form.riskItems.map((item) => item.itemId);
  const termOrder = form.termItems.map((item) => item.itemId);

  return (
    <div className="memo-panel">
      {SECTION_ORDER.map(renderSection)}

      <section className="memo-section">
        <div className="memo-section-head">
          <h3 className="memo-section-title">Risks &amp; Mitigants</h3>
          <button
            type="button"
            className="btn btn-add btn-xs"
            onClick={() => onChange(addMemoRisk(form))}
          >
            Add risk
          </button>
        </div>
        <p className="memo-section-hint">
          Severity and residual risk are your own judgements. Stating a mitigant does not resolve a
          risk or lower its residual label.
        </p>

        {form.riskItems.length === 0 ? (
          <p className="memo-empty">No risks recorded.</p>
        ) : (
          <ul className="memo-item-list">
            {form.riskItems.map((risk) => (
              <li key={risk.itemId} className="memo-item">
                <div className="memo-item-head">
                  <label className="memo-field memo-field-grow">
                    <span className="memo-field-label">Risk</span>
                    <textarea
                      className="memo-textarea"
                      rows={2}
                      value={risk.text}
                      onChange={(event) =>
                        onChange(updateMemoRisk(form, risk.itemId, { text: event.target.value }))
                      }
                    />
                  </label>
                  <RowControls
                    order={riskOrder}
                    itemId={risk.itemId}
                    label="risk"
                    onMove={(direction) => onChange(moveMemoRisk(form, risk.itemId, direction))}
                    onRequestRemove={() => setPendingRemoval(risk.itemId)}
                    removeRef={refFor(risk.itemId)}
                  />
                </div>

                <label className="memo-field">
                  <span className="memo-field-label">Mitigant</span>
                  <textarea
                    className="memo-textarea"
                    rows={2}
                    value={risk.mitigant}
                    onChange={(event) =>
                      onChange(updateMemoRisk(form, risk.itemId, { mitigant: event.target.value }))
                    }
                  />
                </label>

                <div className="memo-field-grid">
                  <label className="memo-field">
                    <span className="memo-field-label">Severity</span>
                    <select
                      className="memo-select"
                      value={risk.severity}
                      onChange={(event) =>
                        onChange(
                          updateMemoRisk(form, risk.itemId, {
                            severity: event.target.value as RiskSeverity,
                          }),
                        )
                      }
                    >
                      {SEVERITY_ORDER.map((value) => (
                        <option key={value} value={value}>
                          {SEVERITY_LABELS[value]}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="memo-field">
                    <span className="memo-field-label">Residual risk</span>
                    <select
                      className="memo-select"
                      value={risk.residualRisk}
                      onChange={(event) =>
                        onChange(
                          updateMemoRisk(form, risk.itemId, {
                            residualRisk: event.target.value as RiskSeverity,
                          }),
                        )
                      }
                    >
                      {SEVERITY_ORDER.map((value) => (
                        <option key={value} value={value}>
                          {SEVERITY_LABELS[value]}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>

                <MemoEvidencePicker
                  evidence={evidence}
                  selectedIds={risk.evidenceIds}
                  claimLabel={risk.text === '' ? 'this risk' : risk.text}
                  onChange={(next) =>
                    onChange(updateMemoRisk(form, risk.itemId, { evidenceIds: next }))
                  }
                />

                {pendingRemoval === risk.itemId && (
                  <RemoveConfirm
                    label="risk"
                    onConfirm={() => {
                      setPendingRemoval(null);
                      onChange(removeMemoRisk(form, risk.itemId));
                    }}
                    onCancel={() => closeConfirm(risk.itemId)}
                  />
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="memo-section">
        <div className="memo-section-head">
          <h3 className="memo-section-title">Terms</h3>
          <button
            type="button"
            className="btn btn-add btn-xs"
            onClick={() => onChange(addMemoTerm(form))}
          >
            Add term
          </button>
        </div>
        <p className="memo-section-hint">
          The terms this transaction is recommended on, and how hard each is held.
        </p>

        {form.termItems.length === 0 ? (
          <p className="memo-empty">No terms recorded.</p>
        ) : (
          <ul className="memo-item-list">
            {form.termItems.map((term) => (
              <li key={term.itemId} className="memo-item">
                <div className="memo-item-head">
                  <label className="memo-field memo-field-grow">
                    <span className="memo-field-label">Term</span>
                    <textarea
                      className="memo-textarea"
                      rows={2}
                      value={term.text}
                      onChange={(event) =>
                        onChange(updateMemoTerm(form, term.itemId, { text: event.target.value }))
                      }
                    />
                  </label>
                  <RowControls
                    order={termOrder}
                    itemId={term.itemId}
                    label="term"
                    onMove={(direction) => onChange(moveMemoTerm(form, term.itemId, direction))}
                    onRequestRemove={() => setPendingRemoval(term.itemId)}
                    removeRef={refFor(term.itemId)}
                  />
                </div>

                <label className="memo-field">
                  <span className="memo-field-label">Priority</span>
                  <select
                    className="memo-select"
                    value={term.priority}
                    onChange={(event) =>
                      onChange(
                        updateMemoTerm(form, term.itemId, {
                          priority: event.target.value as TermPriority,
                        }),
                      )
                    }
                  >
                    {PRIORITY_ORDER.map((value) => (
                      <option key={value} value={value}>
                        {PRIORITY_LABELS[value]}
                      </option>
                    ))}
                  </select>
                </label>

                <MemoEvidencePicker
                  evidence={evidence}
                  selectedIds={term.evidenceIds}
                  claimLabel={term.text === '' ? 'this term' : term.text}
                  onChange={(next) =>
                    onChange(updateMemoTerm(form, term.itemId, { evidenceIds: next }))
                  }
                />

                {pendingRemoval === term.itemId && (
                  <RemoveConfirm
                    label="term"
                    onConfirm={() => {
                      setPendingRemoval(null);
                      onChange(removeMemoTerm(form, term.itemId));
                    }}
                    onCancel={() => closeConfirm(term.itemId)}
                  />
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
