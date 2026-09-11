/**
 * D5.5E -- the one numeric input in the product.
 *
 * Shared by the assumption grid, the rent-roll cells and the suite drawer, so
 * "how a number looks and behaves while you type it" is answered once.
 *
 * **Grouped on blur, plain on focus.** Formatting on every keypress is the
 * version of this feature that everyone regrets: the caret jumps whenever a
 * separator is inserted ahead of it, and editing the middle of a large number
 * becomes a fight. So the analyst always edits the raw digits, and the grouped
 * form appears the moment they look away -- which is exactly when reading
 * matters and editing does not.
 *
 * **A grouped field is `type="text"`.** `<input type="number">` cannot hold
 * `30,000,000`: the browser treats it as invalid and reports an empty value, so
 * the character that makes the number readable is the one that makes it
 * disappear. `inputMode="decimal"` keeps the numeric keypad on touch devices and
 * `step`/spinner behaviour was never used on these fields anyway. Ungrouped
 * fields -- percentages, months, years -- keep `type="number"` exactly as they
 * had it, so nothing changes for them at all.
 *
 * **A whole-field selection survives the swap (D5.9).** Keyboard focus selects
 * the entire displayed value before the focus event fires, so "Tab in, type a
 * new number" replaces it -- ordinary native behaviour. Swapping the grouped
 * display for raw digits is a programmatic value change, and that collapses
 * any selection to a caret at the end: until D5.9, `50,000,000`, Tab, `48000000`
 * became `5000000048000000`. So when the whole display was selected at the
 * moment of focus and the display is about to change, the selection is
 * restored once the raw digits are committed. Nothing is selected that the
 * browser had not already selected: a click, whose caret lands after focus, and
 * a partial selection are both left exactly as they were.
 */

import { useLayoutEffect, useRef, useState } from 'react';
import type { ChangeEvent, CSSProperties } from 'react';
import { groupDigits, stripGroups } from '../numberFormat';

export interface NumericInputProps {
  id: string;
  className: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  /** Show thousands separators while the field is not focused. */
  group: boolean;
  placeholder?: string;
  style?: CSSProperties;
  'aria-label'?: string;
  'aria-invalid'?: true;
  'aria-describedby'?: string;
}

export function NumericInput({
  id,
  className,
  value,
  onChange,
  disabled,
  group,
  placeholder,
  style,
  ...aria
}: NumericInputProps) {
  const [editing, setEditing] = useState(false);
  const grouped = group && !editing;
  const input = useRef<HTMLInputElement>(null);
  const restoreWholeSelection = useRef(false);

  // Runs after React has written the raw digits and before the next keystroke
  // is handled, so the restored selection is the one typing replaces.
  useLayoutEffect(() => {
    if (editing && restoreWholeSelection.current) {
      input.current?.select();
    }
    restoreWholeSelection.current = false;
  }, [editing]);

  return (
    <input
      ref={input}
      id={id}
      className={className}
      // Only a grouped field leaves `type="number"`, and only because it must.
      type={group ? 'text' : 'number'}
      inputMode="decimal"
      step={group ? undefined : 'any'}
      value={grouped ? groupDigits(value) : value}
      disabled={disabled}
      placeholder={placeholder}
      style={style}
      {...aria}
      onFocus={(event) => {
        const field = event.currentTarget;
        restoreWholeSelection.current =
          // Only when the display is about to change under the selection...
          field.value !== value &&
          // ...and the browser had selected all of it.
          field.selectionStart === 0 &&
          field.selectionEnd === field.value.length;
        setEditing(true);
      }}
      onBlur={() => setEditing(false)}
      onChange={(event: ChangeEvent<HTMLInputElement>) =>
        // Stripped on the way in, so form state never holds a separator --
        // including when a grouped number is pasted in.
        onChange(group ? stripGroups(event.target.value) : event.target.value)
      }
    />
  );
}
