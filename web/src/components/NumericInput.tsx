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
 */

import { useState } from 'react';
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

  return (
    <input
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
      onFocus={() => setEditing(true)}
      onBlur={() => setEditing(false)}
      onChange={(event: ChangeEvent<HTMLInputElement>) =>
        // Stripped on the way in, so form state never holds a separator --
        // including when a grouped number is pasted in.
        onChange(group ? stripGroups(event.target.value) : event.target.value)
      }
    />
  );
}
