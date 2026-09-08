/**
 * D5.5E -- display-only thousands grouping for numeric inputs.
 *
 * Human Pass #1: `30000000` is unreadable in a field an analyst is checking at a
 * glance. It should read `30,000,000`, and submit `30000000`.
 *
 * **This is presentation, not arithmetic.** Both functions below are pure string
 * transforms -- a regex inserts separators, a regex removes them. Neither parses
 * a number, so neither can round, clip, or shift a value: there is no numeric
 * type anywhere in this module for a defect to hide in. That is deliberate. The
 * G-M7 audit that forbids frontend financial math finds nothing here to forgive,
 * which is a stronger position than being granted an exception.
 *
 * **Form state never holds a separator.** The grouped string exists only while
 * an input is not focused; the value the form holds, the value the parser reads
 * and the value the wire carries are byte-identical to what they were before
 * this module existed. `stripGroups` runs on the way in so that even a pasted
 * `30,000,000` is normalised before it reaches state.
 */

/**
 * Insert thousands separators into a plain decimal string.
 *
 * Returns the input unchanged when it is not a plain decimal -- an empty field,
 * a half-typed exponent, a stray letter. Anchor never silently repairs input:
 * an unparseable value stays exactly as the analyst left it, and the existing
 * conversion refuses it by name on submit.
 *
 * Preserves everything the analyst typed that carries meaning: the sign, a
 * trailing decimal point mid-entry (`1234.` -> `1,234.`), and every digit after
 * it including trailing zeros (`1.50` stays `1.50`, never `1.5`).
 */
export function groupDigits(raw: string): string {
  const trimmed = raw.trim();
  if (trimmed === '') {
    return '';
  }

  const parsed = /^([+-]?)(\d*)(\.\d*)?$/.exec(trimmed);
  if (parsed === null) {
    return raw;
  }

  const [, sign, whole, fraction = ''] = parsed;
  // Insert a comma at every position that has a multiple of three digits to its
  // right and at least one digit to its left. Pure lookahead -- no counting, no
  // division, no length arithmetic.
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${sign}${grouped}${fraction}`;
}

/** Remove thousands separators, so state and the wire never see one. */
export function stripGroups(text: string): string {
  return text.replace(/,/g, '');
}

/**
 * Whether a field's existing display metadata marks it as an absolute quantity
 * worth grouping.
 *
 * Derived from the `prefix`/`suffix` each field already declares rather than
 * from a list of field names, so a field added to any contract inherits the
 * right behaviour without being registered anywhere.
 *
 * Currency and area group. Percentages, rates, probabilities, month counts and
 * year counts do not -- grouping them would imply a magnitude they never have,
 * and Human Pass #1 asked for commas where they aid reading, not everywhere.
 */
export function groupsThousands(config: { prefix?: string; suffix?: string }): boolean {
  return config.prefix === '$' || config.suffix === 'SF';
}
