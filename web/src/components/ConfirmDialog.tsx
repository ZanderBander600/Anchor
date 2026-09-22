/**
 * Phase 7 Gate P7.10 Stage 4 -- the in-application confirmation.
 *
 * Ratified at the Stage 4 independent review (Correction 2). The gate forbids
 * native browser dialogs, and for good reasons beyond appearance: `confirm()`
 * cannot be labelled for a screen reader, cannot say *what* is at stake in more
 * than one line, blocks the whole page including anything mid-flight, and looks
 * identical whether it is asking about a stray click or about discarding an
 * afternoon's work.
 *
 * This is the replacement, and it is deliberately the only one: a second
 * bespoke confirmation somewhere else would drift from this one.
 *
 * **Accessibility is the substance here, not decoration.**
 *
 * - `role="dialog"` with `aria-modal`, labelled by its own title and described
 *   by its body, so a screen reader announces what is being asked and why.
 * - Focus moves to the **safe** action on open. A destructive default is a
 *   destructive accident waiting for a stray Enter.
 * - Focus is trapped: Tab and Shift+Tab cycle within the dialog, so the
 *   keyboard cannot wander into the page behind it while it is modal.
 * - Escape cancels, which is what every other dialog on the platform does.
 * - Focus returns to the control that opened it, so the keyboard position
 *   survives the interruption.
 * - Cancelling triggers nothing at all -- no navigation, no write.
 */

import { useCallback, useEffect, useRef } from 'react';

export interface ConfirmDialogProps {
  /** What is being asked, in a few words. Names the thing at stake. */
  title: string;
  /** What would happen, in the analyst's terms. */
  body: string;
  /** The destructive action's label -- a verb, never "OK". */
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Everything focusable inside the dialog, in document order. */
const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])';

export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  cancelLabel = 'Cancel',
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  /** The control that had focus when this opened, so it can be given back. */
  const openerRef = useRef<Element | null>(null);

  useEffect(() => {
    openerRef.current = document.activeElement;
    cancelRef.current?.focus();
    return () => {
      // Restored on the way out, whichever way the dialog closed.
      const opener = openerRef.current;
      if (opener instanceof HTMLElement && document.contains(opener)) {
        opener.focus();
      }
    };
  }, []);

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onCancel();
        return;
      }
      if (event.key !== 'Tab') {
        return;
      }
      const focusable = Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [],
      );
      if (focusable.length === 0) {
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      // The trap: wrap at both ends rather than letting focus leave a modal.
      if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    },
    [onCancel],
  );

  return (
    <div className="memo-dialog-scrim">
      <div
        className="memo-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="memo-dialog-title"
        aria-describedby="memo-dialog-body"
        ref={dialogRef}
        onKeyDown={onKeyDown}
      >
        <h2 className="memo-dialog-title" id="memo-dialog-title">
          {title}
        </h2>
        <p className="memo-dialog-body" id="memo-dialog-body">
          {body}
        </p>
        <div className="memo-dialog-actions">
          {/* Cancel first in the DOM and focused on open: the safe action is
            * the one a keyboard reaches without aiming. */}
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={onCancel}
            ref={cancelRef}
          >
            {cancelLabel}
          </button>
          <button type="button" className="btn btn-danger btn-sm" onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
