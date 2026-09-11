/**
 * D5.9 -- keyboard replacement in a grouped `NumericInput`.
 *
 * The D5.9 cross-mode browser pass found that tabbing into a populated grouped
 * field and typing a new number appended to it: `50,000,000`, Tab, `48000000`
 * produced `5,000,000,048,000,000`. Measured in Chromium:
 *
 *   - On keyboard (Tab) focus the browser selects the whole displayed value
 *     *before* the focus event fires -- selection `[0, 10]` of `50,000,000`.
 *   - `NumericInput` then swaps the grouped display for the raw digits. That is
 *     a programmatic value change, and a programmatic value change collapses
 *     the selection to a caret at the end -- `[8, 8]` of `50000000`.
 *   - The typed digits land at that caret.
 *
 * On mouse focus the selection at focus time is *not* the whole field -- the
 * click places its caret afterwards -- so the fix restores a whole-field
 * selection only when one existed at the moment of focus and the display is
 * about to change. It does not select on focus, and it does not try to tell a
 * keyboard from a mouse: it preserves what the browser had already done.
 *
 * `focusAsTheBrowserDoes` reproduces Chromium's order exactly (select, then
 * focus). user-event's `tab()` selects *after* focusing, which is not what the
 * browser does, so it is used only as a second, weaker check.
 */

import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { NumericInput } from './NumericInput';

afterEach(cleanup);

/** A controlled field, driven the way every Anchor form drives it, beside a
 * plain input that Tab can start from. What assertions read as state is what
 * the component *emitted*, never a mirror variable. */
function renderField(initial: string, group: boolean) {
  const onChange = vi.fn<(value: string) => void>();

  function Harness() {
    const [value, setValue] = useState(initial);
    return (
      <>
        <input aria-label="Previous field" />
        <NumericInput
          id="field"
          className="field-input"
          aria-label="Field"
          value={value}
          group={group}
          onChange={(next) => {
            setValue(next);
            onChange(next);
          }}
        />
        <input aria-label="Next field" />
      </>
    );
  }

  render(<Harness />);
  const field = screen.getByLabelText('Field') as HTMLInputElement;
  const emitted = () => {
    const calls = onChange.mock.calls;
    return calls.length === 0 ? initial : calls[calls.length - 1][0];
  };
  return { field, emitted };
}

/** Keyboard focus as Chromium performs it: the whole displayed value is
 * selected first, and only then does the focus event fire. */
function focusAsTheBrowserDoes(field: HTMLInputElement): void {
  act(() => {
    field.setSelectionRange(0, field.value.length);
    field.focus();
  });
}

function selection(field: HTMLInputElement): [number | null, number | null] {
  return [field.selectionStart, field.selectionEnd];
}

// =============================================================================
// 1-5. Tab into a grouped field, type, and the value is replaced
// =============================================================================

describe('a grouped field, entered from the keyboard', () => {
  it('1: shows the grouped value while it is not focused', () => {
    const { field } = renderField('50000000', true);
    expect(field.value).toBe('50,000,000');
  });

  it('2: keeps the whole field selected through the grouped-to-raw swap', () => {
    const { field } = renderField('50000000', true);

    focusAsTheBrowserDoes(field);

    // The display changed under the selection, and the selection survived it.
    expect(field.value).toBe('50000000');
    expect(selection(field)).toEqual([0, 8]);
  });

  it('3, 4, 5: typing replaces the value rather than appending to it', async () => {
    const user = userEvent.setup({ delay: null });
    const { field, emitted } = renderField('50000000', true);

    focusAsTheBrowserDoes(field);
    await user.keyboard('48000000');

    // The defect, in one assertion: this read 5000000048000000.
    expect(field.value).toBe('48000000');
    expect(emitted()).toBe('48000000');

    await user.tab();
    expect(field.value).toBe('48,000,000');
    // State never holds a separator.
    expect(emitted()).toBe('48000000');
  });

  it('3: user-event Tab also replaces', async () => {
    const user = userEvent.setup({ delay: null });
    const { field, emitted } = renderField('50000000', true);

    await user.click(screen.getByLabelText('Previous field'));
    await user.tab();
    expect(document.activeElement).toBe(field);
    await user.keyboard('48000000');
    await user.tab();

    expect(field.value).toBe('48,000,000');
    expect(emitted()).toBe('48000000');
  });

  it('leaves an empty grouped field alone', async () => {
    const user = userEvent.setup({ delay: null });
    const { field, emitted } = renderField('', true);

    focusAsTheBrowserDoes(field);
    await user.keyboard('1250000');
    await user.tab();

    expect(field.value).toBe('1,250,000');
    expect(emitted()).toBe('1250000');
  });
});

// =============================================================================
// 6, 7. Pointer editing is untouched
// =============================================================================

describe('a grouped field, entered with the pointer', () => {
  it('6: a click places a caret; it does not force a whole-field selection', async () => {
    const user = userEvent.setup({ delay: null });
    const { field } = renderField('50000000', true);

    await user.click(field);

    expect(field.value).toBe('50000000');
    const [start, end] = selection(field);
    expect(start).toBe(end);
  });

  it('6: a partial selection at focus is not widened to the whole field', () => {
    const { field } = renderField('50000000', true);

    act(() => {
      field.setSelectionRange(3, 6);
      field.focus();
    });

    expect(field.value).toBe('50000000');
    expect(selection(field)).not.toEqual([0, 8]);
  });

  it('7: Ctrl+A then typing still replaces', async () => {
    const user = userEvent.setup({ delay: null });
    const { field, emitted } = renderField('50000000', true);

    await user.click(field);
    await user.keyboard('{Control>}a{/Control}47000000');
    await user.tab();

    expect(field.value).toBe('47,000,000');
    expect(emitted()).toBe('47000000');
  });

  it('7: a focus re-selection does not recur on the next, unselected focus', async () => {
    // The restoration is one-shot. A later click into the same field -- after a
    // keyboard entry restored a selection once -- gets an ordinary caret.
    const user = userEvent.setup({ delay: null });
    const { field } = renderField('50000000', true);

    focusAsTheBrowserDoes(field);
    await user.tab();
    await user.click(field);

    const [start, end] = selection(field);
    expect(start).toBe(end);
  });
});

// =============================================================================
// 8, 9. Ungrouped fields keep their exact pre-D5.9 behaviour
// =============================================================================

describe('an ungrouped field (percentages, months, years)', () => {
  it.each([
    ['a percentage', '5.25', '6.5'],
    ['a month count', '60', '84'],
  ])('8, 9: %s is a number field whose display never changes', async (_, initial, next) => {
    const user = userEvent.setup({ delay: null });
    const { field, emitted } = renderField(initial, false);

    expect(field.type).toBe('number');
    expect(field.value).toBe(initial);

    await user.click(field);
    expect(field.value).toBe(initial);
    await user.keyboard(`{Control>}a{/Control}${next}`);
    await user.tab();

    expect(field.value).toBe(next);
    expect(emitted()).toBe(next);
  });

  it('9: a large ungrouped value is never grouped', async () => {
    const user = userEvent.setup({ delay: null });
    const { field } = renderField('1500', false);

    await user.click(field);
    await user.tab();

    expect(field.value).toBe('1500');
  });
});
