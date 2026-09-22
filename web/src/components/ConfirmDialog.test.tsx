/**
 * Phase 7 Gate P7.10 Stage 4 -- the in-application confirmation.
 *
 * Ratified at the Stage 4 independent review (Correction 2). The requirement
 * was specific, so these tests are specific: the dialog names what is at stake,
 * says what would be lost, defaults focus to the safe action, supports Escape,
 * traps focus, restores focus to the control that opened it, proceeds only when
 * confirmed, and navigates nothing when cancelled.
 *
 * The last two are proved through `App`'s own memo switch in
 * `web/src/memoSwitch.test.tsx`; what is proved here is the dialog itself.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { ConfirmDialog } from './ConfirmDialog';

afterEach(cleanup);

/** The accessible name or description a screen reader would announce, resolved
 * the way the platform resolves it: through the id the dialog points at.
 * `jest-dom` is not a dependency of this project, so this is done by hand. */
function announced(dialog: HTMLElement, relation: 'aria-labelledby' | 'aria-describedby'): string {
  const id = dialog.getAttribute(relation) ?? '';
  return document.getElementById(id)?.textContent ?? '';
}

function renderDialog(overrides: Partial<Parameters<typeof ConfirmDialog>[0]> = {}) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(
    <ConfirmDialog
      title="Open Harbor Point?"
      body="Riverside Commons has unsaved changes that have not been saved. Opening Harbor Point discards them."
      confirmLabel="Discard and open"
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...overrides}
    />,
  );
  return { onConfirm, onCancel };
}

describe('P7.10 Stage 4 -- ConfirmDialog', () => {
  it('is announced as a modal dialog, named and described', () => {
    renderDialog();
    const dialog = screen.getByRole('dialog');

    expect(dialog.getAttribute('aria-modal')).toBe('true');
    // Its name is the question, and its description is the consequence: a
    // screen reader hears both without the user hunting for them.
    expect(announced(dialog, 'aria-labelledby')).toBe('Open Harbor Point?');
    expect(announced(dialog, 'aria-describedby')).toBe(
      'Riverside Commons has unsaved changes that have not been saved. Opening Harbor Point discards them.',
    );
  });

  it('names the memo, the destination and what would be lost', () => {
    renderDialog();
    const text = screen.getByRole('dialog').textContent ?? '';

    expect(text).toContain('Harbor Point'); // where the analyst is going
    expect(text).toContain('Riverside Commons'); // what they are leaving
    expect(text).toContain('unsaved changes'); // what is at stake
    expect(text).toContain('discards them'); // in plain words
  });

  it('focuses the safe action on open, never the destructive one', () => {
    renderDialog();

    // A stray Enter must not discard an afternoon's work.
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Cancel' }));
    expect(document.activeElement).not.toBe(
      screen.getByRole('button', { name: 'Discard and open' }),
    );
  });

  it('confirms only when the destructive action is chosen', async () => {
    const { onConfirm, onCancel } = renderDialog();

    await userEvent.click(screen.getByRole('button', { name: 'Discard and open' }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it('cancelling triggers nothing but the cancel', async () => {
    const { onConfirm, onCancel } = renderDialog();

    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('Escape cancels', async () => {
    const { onConfirm, onCancel } = renderDialog();

    await userEvent.keyboard('{Escape}');

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('traps focus, so the keyboard cannot wander behind the modal', async () => {
    renderDialog();
    const cancel = screen.getByRole('button', { name: 'Cancel' });
    const confirm = screen.getByRole('button', { name: 'Discard and open' });

    expect(document.activeElement).toBe(cancel);
    await userEvent.tab();
    expect(document.activeElement).toBe(confirm);
    // Past the last control, focus wraps to the first rather than leaving.
    await userEvent.tab();
    expect(document.activeElement).toBe(cancel);
    // And backwards, off the front, it wraps to the last.
    await userEvent.tab({ shift: true });
    expect(document.activeElement).toBe(confirm);
  });

  it('gives focus back to the control that opened it', async () => {
    function Host() {
      const [open, setOpen] = useState(false);
      return (
        <div>
          <button type="button" onClick={() => setOpen(true)}>
            Open Harbor Point
          </button>
          {open && (
            <ConfirmDialog
              title="Open Harbor Point?"
              body="Riverside Commons has unsaved changes."
              confirmLabel="Discard and open"
              onConfirm={() => setOpen(false)}
              onCancel={() => setOpen(false)}
            />
          )}
        </div>
      );
    }

    render(<Host />);
    const opener = screen.getByRole('button', { name: 'Open Harbor Point' });
    await userEvent.click(opener);
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Cancel' }));

    await userEvent.keyboard('{Escape}');

    // The keyboard position survives the interruption.
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it('the destructive action is a verb, and the safe one is reachable first', () => {
    renderDialog();
    const buttons = screen.getAllByRole('button').map((button) => button.textContent);

    // Cancel is first in the DOM, so it is what a keyboard reaches without
    // aiming; CSS places it last visually.
    expect(buttons).toEqual(['Cancel', 'Discard and open']);
    // Never "OK": the label says what will happen.
    expect(buttons).not.toContain('OK');
  });
});
